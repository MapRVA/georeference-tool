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
from django.db.models import F, Q
from django.utils import timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from images.models import SiteSettings

from .models import OsmElement, Subject, WikidataItem

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
    """
    Perform the actual refresh of a WikidataItem.
    """

    logger.info(f"Refreshing WikidataItem {item.wikidata_id}")

    # Mark as fetched immediately to prevent concurrent tasks from picking this up
    item.metadata_last_fetched = timezone.now()
    item.save(update_fields=["metadata_last_fetched"])

    try:
        success = item.populate_from_wikidata()

        if success:
            item.metadata_fetch_failures = 0
            item.save()
            logger.info(f"Successfully refreshed WikidataItem {item.wikidata_id}")
            return {"status": "success", "wikidata_id": item.wikidata_id}
        else:
            item.metadata_fetch_failures = F("metadata_fetch_failures") + 1
            item.save(update_fields=["metadata_fetch_failures"])
            logger.warning(f"No data returned for WikidataItem {item.wikidata_id}")
            return {"status": "no_data", "wikidata_id": item.wikidata_id}

    except Exception as e:
        WikidataItem.objects.filter(pk=item.pk).update(
            metadata_fetch_failures=F("metadata_fetch_failures") + 1,
        )
        logger.error(f"Error refreshing WikidataItem {item.wikidata_id}: {e}")
        return {"status": "error", "wikidata_id": item.wikidata_id, "message": str(e)}


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

    except Exception as e:
        logger.error(f"Error populating OSM for {subject.title}: {e}")
        return {"status": "error", "subject": subject.title, "message": str(e)}

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

    except Exception as e:
        logger.error(f"Error refreshing OSM for {subject.title}: {e}")
        return {"status": "error", "subject": subject.title, "message": str(e)}

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
    """Find the next WikidataItem that needs refreshing."""

    stale_hours = get_stale_threshold_hours()
    max_failures = get_max_failures()
    stale_threshold = timezone.now() - timedelta(hours=stale_hours)

    return (
        WikidataItem.objects.filter(
            Q(metadata_last_fetched__isnull=True)
            | Q(metadata_last_fetched__lt=stale_threshold),
            metadata_fetch_failures__lt=max_failures,
        )
        .order_by("metadata_last_fetched")
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
