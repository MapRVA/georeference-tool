"""
Signal handlers for keeping the tile materialized view up-to-date.

These handlers automatically refresh the public_georeferences_mvt materialized view
when data that affects it changes.

The view only needs to refresh when:
- A Georeference is created, updated, or deleted
- A Collection's 'public' status changes
- A Source's 'public' status changes
"""

import logging
from django.db import connection, transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Georeference, Collection, Source

logger = logging.getLogger(__name__)


def refresh_tile_view(using_concurrent=True):
    """
    Refresh the public_georeferences_mvt materialized view.

    Args:
        using_concurrent (bool): Use CONCURRENT refresh (non-blocking).
                                 Requires unique index on the view.
    """
    try:
        method = (
            "REFRESH MATERIALIZED VIEW CONCURRENTLY"
            if using_concurrent
            else "REFRESH MATERIALIZED VIEW"
        )
        with connection.cursor() as cursor:
            cursor.execute(f"{method} public_georeferences_mvt")
        logger.debug(f"Successfully refreshed public_georeferences_mvt ({method})")
    except Exception as e:
        # Log warning but don't raise - the view will be eventually consistent
        logger.warning(f"Failed to refresh tile view: {str(e)}")


@receiver(post_save, sender=Georeference)
def refresh_view_on_georeference_save(sender, instance, created, **kwargs):
    """
    Refresh materialized view when a georeference is created or updated.
    """
    transaction.on_commit(lambda: refresh_tile_view(using_concurrent=True))


@receiver(post_delete, sender=Georeference)
def refresh_view_on_georeference_delete(sender, instance, **kwargs):
    """
    Refresh materialized view when a georeference is deleted.
    """
    transaction.on_commit(lambda: refresh_tile_view(using_concurrent=True))


@receiver(post_save, sender=Collection)
def refresh_view_on_collection_save(sender, instance, **kwargs):
    """
    Refresh materialized view when a collection's public status changes.
    """
    # Check if the public field was updated
    # If update_fields is None, all fields were potentially updated
    update_fields = kwargs.get("update_fields")
    if update_fields is None or "public" in update_fields:
        transaction.on_commit(lambda: refresh_tile_view(using_concurrent=True))


@receiver(post_save, sender=Source)
def refresh_view_on_source_save(sender, instance, **kwargs):
    """
    Refresh materialized view when a source's public status changes.
    """
    # Check if the public field was updated
    # If update_fields is None, all fields were potentially updated
    update_fields = kwargs.get("update_fields")
    if update_fields is None or "public" in update_fields:
        transaction.on_commit(lambda: refresh_tile_view(using_concurrent=True))
