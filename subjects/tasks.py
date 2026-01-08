"""
Celery tasks for refreshing external metadata (Wikidata, OSM).

Rate limiting is achieved through Celery Beat scheduling: Beat triggers
each refresh task at a fixed interval (e.g., every 15 seconds for 4/minute),
ensuring global rate limits regardless of worker count.
"""

import json
import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.db.models import F, Q
from django.utils import timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import OsmElement, WikidataItem

logger = logging.getLogger(__name__)


def get_stale_threshold_days():
    """Get the number of days after which metadata is considered stale."""
    return getattr(settings, "METADATA_REFRESH_STALE_DAYS", 30)


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

    try:
        success = item.populate_from_wikidata()
        item.metadata_last_fetched = timezone.now()

        if success:
            item.metadata_fetch_failures = 0
            item.save()
            logger.info(f"Successfully refreshed WikidataItem {item.wikidata_id}")
            return {"status": "success", "wikidata_id": item.wikidata_id}
        else:
            item.metadata_fetch_failures = F("metadata_fetch_failures") + 1
            item.save(
                update_fields=["metadata_last_fetched", "metadata_fetch_failures"]
            )
            logger.warning(f"No data returned for WikidataItem {item.wikidata_id}")
            return {"status": "no_data", "wikidata_id": item.wikidata_id}

    except Exception as e:
        WikidataItem.objects.filter(pk=item.pk).update(
            metadata_last_fetched=timezone.now(),
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
    """Get the bounding box clause for Postpass queries."""
    return getattr(
        settings,
        "METADATA_REFRESH_POSTPASS_BBOX",
        "ST_SetSRID(ST_MakeBox2D(ST_MakePoint(-84.72, 35.90), ST_MakePoint(-74.97, 39.71)), 4326)",
    )


def _do_refresh_osm_element(element):
    """
    Perform the actual refresh of an OsmElement.
    """

    # Get the Wikidata ID from linked subjects
    subject = element.subjects.filter(wikidata_item__isnull=False).first()
    if not subject or not subject.wikidata_item:
        logger.warning(f"OsmElement {element.osm_id} has no linked Wikidata item")
        element.metadata_last_fetched = timezone.now()
        element.save(update_fields=["metadata_last_fetched"])
        return {"status": "skipped", "message": "No linked Wikidata item"}

    wikidata_id = subject.wikidata_item.wikidata_id
    logger.info(f"Refreshing OsmElement {element.osm_id} via Wikidata {wikidata_id}")

    session = create_request_session()
    try:
        features = fetch_osm_features(session, wikidata_id)
        element.metadata_last_fetched = timezone.now()

        if not features:
            element.metadata_fetch_failures = F("metadata_fetch_failures") + 1
            element.save(
                update_fields=["metadata_last_fetched", "metadata_fetch_failures"]
            )
            logger.warning(f"No OSM features found for {wikidata_id}")
            return {"status": "no_data", "osm_id": element.osm_id}

        # Find the feature matching our osm_id, or use the first one
        matching_feature = None
        for feature in features:
            if feature["properties"].get("osm_id") == element.osm_id:
                matching_feature = feature
                break

        if not matching_feature:
            # OSM ID might have changed; use first feature but log it
            matching_feature = features[0]
            new_osm_id = matching_feature["properties"].get("osm_id")
            if new_osm_id and new_osm_id != element.osm_id:
                logger.info(
                    f"OSM ID changed from {element.osm_id} to {new_osm_id} for {wikidata_id}"
                )
                element.osm_id = new_osm_id

        # Update geometry
        geometry = matching_feature["geometry"]
        element.geometry = GEOSGeometry(json.dumps(geometry))
        element.metadata_fetch_failures = 0
        element.save()

        logger.info(f"Successfully refreshed OsmElement {element.osm_id}")
        return {"status": "success", "osm_id": element.osm_id}

    except Exception as e:
        OsmElement.objects.filter(pk=element.pk).update(
            metadata_last_fetched=timezone.now(),
            metadata_fetch_failures=F("metadata_fetch_failures") + 1,
        )
        logger.error(f"Error refreshing OsmElement {element.osm_id}: {e}")
        return {"status": "error", "osm_id": element.osm_id, "message": str(e)}

    finally:
        session.close()


def fetch_osm_features(session, wikidata_id: str) -> list:
    """Fetch OSM features from Postpass API for a Wikidata item."""
    postpass_url = get_postpass_url()
    timeout = get_postpass_timeout()
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

    stale_days = get_stale_threshold_days()
    max_failures = get_max_failures()
    stale_threshold = timezone.now() - timedelta(days=stale_days)

    return (
        WikidataItem.objects.filter(
            Q(metadata_last_fetched__isnull=True)
            | Q(metadata_last_fetched__lt=stale_threshold),
            metadata_fetch_failures__lt=max_failures,
        )
        .order_by("metadata_last_fetched")
        .first()
    )


def get_next_stale_osm_element():
    """Find the next OsmElement that needs refreshing."""

    stale_days = get_stale_threshold_days()
    max_failures = get_max_failures()
    stale_threshold = timezone.now() - timedelta(days=stale_days)

    return (
        OsmElement.objects.filter(
            Q(metadata_last_fetched__isnull=True)
            | Q(metadata_last_fetched__lt=stale_threshold),
            metadata_fetch_failures__lt=max_failures,
        )
        .order_by("metadata_last_fetched")
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
    Refresh a single stale OsmElement.

    Called periodically by Celery Beat at the configured rate limit interval.
    This approach ensures global rate limiting regardless of worker count.
    """
    element = get_next_stale_osm_element()
    if element is None:
        logger.debug("No stale OsmElements to refresh")
        return {"status": "idle", "message": "No stale elements"}

    # Perform the refresh inline (not queued) since Beat controls the rate
    return _do_refresh_osm_element(element)
