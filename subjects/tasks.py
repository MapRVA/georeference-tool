"""
Celery tasks for refreshing external metadata (Wikidata, OSM).

Rate limiting is achieved through Celery Beat scheduling: Beat triggers
each refresh task at a fixed interval (e.g., every 15 seconds for 4/minute),
ensuring global rate limits regardless of worker count.
"""

import json
import logging
import re
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from images.models import SiteSettings

from .memgraph import GRAPH_ERRORS, MemgraphClient
from .models import OsmElement, Subject, WikidataItem
from .project_graph import rebuild_project_graph
from .subject_ancestors import update_subject_ancestors
from .wikidata_closure import (
    SEED_METADATA_FIELDS,
    ClosureLoadError,
    commit_closure_to_memgraph,
    fetch_seed_data,
)

logger = logging.getLogger(__name__)


def get_stale_threshold_hours():
    """Get the number of hours after which metadata is considered stale."""
    return getattr(settings, "METADATA_REFRESH_STALE_HOURS", 24)


def get_max_failures():
    """Get the maximum consecutive failures before stopping retries."""
    return getattr(settings, "METADATA_REFRESH_MAX_FAILURES", 5)


def create_request_session():
    """Create a requests session with retry strategy."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# =============================================================================
# Wikidata Refresh Tasks
# =============================================================================


def _do_refresh_wikidata_item(item):
    """Re-pull a WikidataItem's closure from WDQS and refresh its mirror.

    One CONSTRUCT to WDQS gives us the seed's metadata fields and its
    closure neighbourhood; the seed row gets the metadata, each entity's
    Memgraph mirror gets atomically swapped, and ancestors discovered
    along the way are linked back to the seed's Subject via
    ``discovered_via``.
    """

    logger.info(f"Refreshing WikidataItem {item.wikidata_id}")

    # Bump the freshness timestamp up front so a concurrent Beat tick
    # doesn't pick the same row while we're talking to WDQS. Targeted
    # UPDATE avoids the full-row save that ``item.save()`` does.
    now = timezone.now()
    WikidataItem.objects.filter(pk=item.pk).update(sparql_last_loaded_at=now)
    item.sparql_last_loaded_at = now

    try:
        data = fetch_seed_data(item.wikidata_id)
    except requests.RequestException as e:
        WikidataItem.objects.filter(pk=item.pk).update(
            sparql_fetch_failures=F("sparql_fetch_failures") + 1,
        )
        logger.error(f"WDQS fetch failed for {item.wikidata_id}: {e}")
        return {"status": "error", "wikidata_id": item.wikidata_id, "message": str(e)}
    except ClosureLoadError as e:
        WikidataItem.objects.filter(pk=item.pk).update(
            sparql_fetch_failures=F("sparql_fetch_failures") + 1,
        )
        logger.warning(f"Unusable closure for {item.wikidata_id}: {e}")
        return {"status": "no_data", "wikidata_id": item.wikidata_id}

    try:
        seed_subject = item.subject
    except Subject.DoesNotExist:
        seed_subject = None

    try:
        with transaction.atomic():
            item._apply_seed_metadata(data["metadata"])
            item.sparql_last_loaded_at = timezone.now()
            item.sparql_fetch_failures = 0
            item.save(update_fields=list(SEED_METADATA_FIELDS))
            commit_closure_to_memgraph(
                item.wikidata_id,
                data["groups"],
                data["labels"],
                discovered_via=seed_subject,
            )
    except GRAPH_ERRORS as e:
        WikidataItem.objects.filter(pk=item.pk).update(
            sparql_fetch_failures=F("sparql_fetch_failures") + 1,
        )
        logger.error(f"Memgraph update failed for {item.wikidata_id}: {e}")
        return {"status": "error", "wikidata_id": item.wikidata_id, "message": str(e)}

    # Project the seed's category ancestors into Postgres. Best-effort:
    # if this fails we keep the successful Memgraph commit, and the next
    # refresh of the same Subject will re-attempt the projection.
    if seed_subject is not None:
        try:
            with MemgraphClient() as client:
                update_subject_ancestors(seed_subject, client)
        except GRAPH_ERRORS as e:
            logger.warning(
                "SubjectAncestor refresh failed for %s: %s — "
                "will retry on next refresh of this Subject",
                item.wikidata_id,
                e,
            )

    logger.info(f"Successfully refreshed WikidataItem {item.wikidata_id}")
    return {"status": "success", "wikidata_id": item.wikidata_id}


# =============================================================================
# OSM Refresh Tasks
# =============================================================================


def get_postpass_url():
    """Get Postpass API URL from settings."""
    return getattr(
        settings,
        "METADATA_REFRESH_POSTPASS_URL",
        "https://postpass.geofabrik.de/api/0.2/interpreter",
    )


def get_postpass_timeout():
    """Get Postpass API timeout from settings."""
    return getattr(settings, "METADATA_REFRESH_POSTPASS_TIMEOUT", 60)


def get_postpass_bbox():
    """Build the bounding box SQL clause for Postpass queries from SiteSettings."""
    site_settings = SiteSettings.load()
    return (
        f"ST_SetSRID(ST_MakeBox2D("
        f"ST_MakePoint({site_settings.default_subject_bbox_west}, {site_settings.default_subject_bbox_south}), "
        f"ST_MakePoint({site_settings.default_subject_bbox_east}, {site_settings.default_subject_bbox_north})"
        f"), 4326)"
    )


def _do_populate_osm_for_subject(subject):
    """
    Populate OSM elements for a subject that has a Wikidata item but no OSM elements.

    Creates an OsmElement for each OSM feature found with the subject's Wikidata ID.
    This handles cases like roads that span multiple OSM ways.
    """
    wikidata_id = subject.wikidata_item.wikidata_id
    logger.info(f"Populating OSM elements for {subject.title} ({wikidata_id})")

    # Mark as checked immediately to prevent concurrent tasks from picking this up
    subject.osm_last_checked = timezone.now()
    subject.save(update_fields=["osm_last_checked"])

    session = create_request_session()
    try:
        features = fetch_osm_features(session, wikidata_id)

        if not features:
            logger.info(f"No OSM features found for {subject.title} ({wikidata_id})")
            return {"status": "no_data", "subject": subject.title}

        osm_ids = []
        for feature in features:
            osm_id = feature["properties"]["osm_id"]
            geometry = feature["geometry"]

            # Create or get existing OsmElement and link to subject
            osm_element, created = OsmElement.objects.get_or_create(
                osm_id=osm_id,
                defaults={
                    "subject": subject,
                    "geometry": GEOSGeometry(json.dumps(geometry)),
                },
            )

            if not created:
                # Update geometry and subject if element already exists
                osm_element.subject = subject
                osm_element.geometry = GEOSGeometry(json.dumps(geometry))
                osm_element.save()
                logger.info(
                    f"Updated existing OSM element {osm_id} for {subject.title}"
                )
            else:
                logger.info(f"Created OSM element {osm_id} for {subject.title}")

            osm_ids.append(osm_id)

        logger.info(f"Linked {len(osm_ids)} OSM element(s) to {subject.title}")

        return {"status": "success", "subject": subject.title, "osm_ids": osm_ids}

    finally:
        session.close()


def _do_refresh_osm_for_subject(subject):
    """
    Refresh all OSM elements for a subject.

    Fetches fresh data from OSM and updates/creates/deletes OsmElements as needed.
    This refreshes all elements for the subject in a single API call.
    """
    if not subject.wikidata_item:
        logger.warning(f"Subject {subject.title} has no Wikidata item")
        return {"status": "skipped", "message": "No Wikidata item"}

    wikidata_id = subject.wikidata_item.wikidata_id
    logger.info(f"Refreshing OSM elements for {subject.title} ({wikidata_id})")

    # Mark subject as checked immediately to prevent concurrent tasks
    subject.osm_last_checked = timezone.now()
    subject.save(update_fields=["osm_last_checked"])

    session = create_request_session()
    try:
        features = fetch_osm_features(session, wikidata_id)

        if not features:
            # No features found - delete all existing OSM elements for this subject
            deleted_count = subject.osm_elements.count()
            if deleted_count > 0:
                subject.osm_elements.all().delete()
                logger.info(
                    f"Deleted {deleted_count} OSM element(s) for {subject.title} (no longer in OSM)"
                )
            else:
                logger.info(f"No OSM features found for {subject.title}")
            return {
                "status": "no_data",
                "subject": subject.title,
                "deleted": deleted_count,
            }

        # Get current OSM IDs for this subject
        current_osm_ids = set(subject.osm_elements.values_list("osm_id", flat=True))
        new_osm_ids = {f["properties"]["osm_id"] for f in features}

        # Delete OSM elements that are no longer in the API response
        stale_osm_ids = current_osm_ids - new_osm_ids
        deleted_count = 0
        if stale_osm_ids:
            deleted_count = subject.osm_elements.filter(
                osm_id__in=stale_osm_ids
            ).delete()[0]
            logger.info(
                f"Deleted {deleted_count} stale OSM element(s) for {subject.title}"
            )

        # Create or update OsmElements for all features
        created_count = 0
        updated_count = 0
        for feature in features:
            osm_id = feature["properties"]["osm_id"]
            geometry = feature["geometry"]

            osm_element, created = OsmElement.objects.get_or_create(
                osm_id=osm_id,
                defaults={
                    "subject": subject,
                    "geometry": GEOSGeometry(json.dumps(geometry)),
                },
            )

            if not created:
                osm_element.subject = subject
                osm_element.geometry = GEOSGeometry(json.dumps(geometry))
                osm_element.save()
                updated_count += 1
            else:
                created_count += 1

        logger.info(
            f"Refreshed OSM elements for {subject.title}: "
            f"created {created_count}, updated {updated_count}, deleted {deleted_count}"
        )
        return {
            "status": "success",
            "subject": subject.title,
            "created": created_count,
            "updated": updated_count,
            "deleted": deleted_count,
        }

    finally:
        session.close()


def fetch_osm_features(
    session,
    wikidata_id: str,
    postpass_url: str | None = None,
    timeout: int | None = None,
) -> list:
    """Fetch OSM features from Postpass API for a Wikidata item.

    Args:
        session: requests Session object
        wikidata_id: Wikidata ID (e.g., Q42)
        postpass_url: Optional override for Postpass API URL (defaults to settings)
        timeout: Optional override for request timeout (defaults to settings)
    """
    # Validate wikidata_id format to prevent SQL injection
    # Wikidata IDs are always Q followed by one or more digits (e.g., Q42, Q12345)
    if not re.match(r"^Q\d+$", wikidata_id):
        raise ValueError(f"Invalid Wikidata ID format: {wikidata_id}")

    postpass_url = postpass_url or get_postpass_url()
    timeout = timeout or get_postpass_timeout()
    bbox_clause = get_postpass_bbox()

    sql_query = f"""
    SELECT osm_id, tags, geom FROM postpass_pointlinepolygon
    WHERE tags->>'wikidata' = '{wikidata_id}' AND geom && {bbox_clause}
    """

    response = session.post(
        postpass_url,
        data={"data": sql_query},
        timeout=timeout,
        headers={
            "User-Agent": "GeoreferenceTool/1.0 (https://github.com/mapRVA/georeference-tool)"
        },
    )
    response.raise_for_status()

    data = response.json()
    features = data.get("features", [])

    # Ensure osm_id is in properties
    for feature in features:
        if "osm_id" not in feature.get("properties", {}):
            feature["properties"]["osm_id"] = feature["properties"].get("osm_id", 0)

    return features


# =============================================================================
# Coordinator Tasks (Beat-driven rate limiting)
# =============================================================================


def get_next_stale_wikidata_item():
    """
    Find the next WikidataItem whose graph closure needs refreshing.

    Only items attached to a Subject are refreshed on their own schedule.
    Ancestor items discovered via closure fetches don't need one: their
    mirrored data is replaced whenever a seed's closure includes them, and
    ``commit_closure_to_memgraph`` bumps their freshness timestamps then.
    Enrolling them here made the rotation unbounded — each ancestor refresh
    fetched *its* closure, discovering ever-deeper ancestors, until the
    queue (200k+ items) could never drain within the staleness window.
    """

    stale_hours = get_stale_threshold_hours()
    max_failures = get_max_failures()
    stale_threshold = timezone.now() - timedelta(hours=stale_hours)

    return (
        WikidataItem.objects.filter(
            Q(sparql_last_loaded_at__isnull=True)
            | Q(sparql_last_loaded_at__lt=stale_threshold),
            sparql_fetch_failures__lt=max_failures,
            subject__isnull=False,
        )
        .order_by("sparql_last_loaded_at")
        .first()
    )


def get_next_subject_needing_osm():
    """Find the next Subject that has a Wikidata item but no OSM elements yet.

    Excludes subjects that have been checked recently (within stale threshold).
    """
    stale_hours = get_stale_threshold_hours()
    stale_threshold = timezone.now() - timedelta(hours=stale_hours)

    return (
        Subject.objects.filter(
            wikidata_item__isnull=False,
            osm_elements__isnull=True,
        )
        .filter(
            Q(osm_last_checked__isnull=True) | Q(osm_last_checked__lt=stale_threshold)
        )
        .order_by("osm_last_checked", "created_at")
        .first()
    )


def get_next_subject_needing_osm_refresh():
    """Find the next Subject with OSM elements that need refreshing.

    Returns subjects that have OSM elements and either:
    - osm_last_checked is null, or
    - osm_last_checked is older than the stale threshold
    """
    stale_hours = get_stale_threshold_hours()
    stale_threshold = timezone.now() - timedelta(hours=stale_hours)

    return (
        Subject.objects.filter(
            wikidata_item__isnull=False,
            osm_elements__isnull=False,
        )
        .filter(
            Q(osm_last_checked__isnull=True) | Q(osm_last_checked__lt=stale_threshold)
        )
        .distinct()
        .order_by("osm_last_checked")
        .first()
    )


@shared_task(ignore_result=True)
def refresh_next_wikidata_item():
    """
    Refresh a single stale WikidataItem.

    Called periodically by Celery Beat at the configured rate limit interval.
    This approach ensures global rate limiting regardless of worker count.
    """
    item = get_next_stale_wikidata_item()
    if item is None:
        logger.debug("No stale WikidataItems to refresh")
        return {"status": "idle", "message": "No stale items"}

    # Perform the refresh inline (not queued) since Beat controls the rate
    return _do_refresh_wikidata_item(item)


@shared_task(ignore_result=True)
def hydrate_wikidata_item(wikidata_id):
    """Load a single WikidataItem's closure into Memgraph.

    Enqueued from ``WikidataItem.save()`` on the urgent queue after the
    cheap entity-JSON validation has already created the row. Same body
    as the Beat-driven refresher; if this task is dropped or fails, the
    Beat tick will eventually pick the row up (it still has
    ``sparql_last_loaded_at IS NULL``).
    """
    item = WikidataItem.objects.filter(wikidata_id=wikidata_id).first()
    if item is None:
        logger.warning(f"hydrate_wikidata_item: no row for {wikidata_id}")
        return {"status": "missing", "wikidata_id": wikidata_id}
    return _do_refresh_wikidata_item(item)


@shared_task(ignore_result=True)
def refresh_next_osm_element():
    """
    Populate or refresh OSM element data for a subject.

    Called periodically by Celery Beat at the configured rate limit interval.
    This approach ensures global rate limiting regardless of worker count.

    Priority:
    1. First, populate OSM elements for subjects that have Wikidata items but no OSM elements
    2. Then, refresh OSM elements for subjects that have stale data
    """
    # Priority 1: Subjects needing initial OSM population
    subject = get_next_subject_needing_osm()
    if subject is not None:
        return _do_populate_osm_for_subject(subject)

    # Priority 2: Subjects with stale OSM elements needing refresh
    subject = get_next_subject_needing_osm_refresh()
    if subject is not None:
        return _do_refresh_osm_for_subject(subject)

    logger.debug("No OSM elements to populate or refresh")
    return {"status": "idle", "message": "No elements to process"}


@shared_task(ignore_result=True)
def reconcile_project_graph():
    """Wholesale-rebuild the project-subject markers from Subject rows.

    The markers are maintained incrementally by post_save/post_delete
    signals, but those don't backfill after a fresh Memgraph volume or
    cover signal failures. This periodic reconcile self-heals any drift.
    """
    count = rebuild_project_graph()
    return {"status": "success", "markers": count}
