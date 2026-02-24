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
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Collection, Georeference, Image, Source
from .views.api import bump_tile_version

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


def refresh_tiles(using_concurrent=True):
    """
    Refresh the materialized view, then bump the tile version.

    The version must be bumped AFTER the view refresh completes, otherwise
    the new version's tiles may be served (and cached) with stale data.
    """

    refresh_tile_view(using_concurrent)
    bump_tile_version()


@receiver(post_save, sender=Georeference)
def refresh_view_on_georeference_save(sender, instance, created, **kwargs):
    """
    Refresh materialized view and invalidate tile cache when a georeference
    is created or updated.
    """
    transaction.on_commit(refresh_tiles)


@receiver(post_delete, sender=Georeference)
def refresh_view_on_georeference_delete(sender, instance, **kwargs):
    """
    Refresh materialized view and invalidate tile cache when a georeference
    is deleted.
    """
    transaction.on_commit(refresh_tiles)


@receiver(post_save, sender=Collection)
def refresh_view_on_collection_save(sender, instance, **kwargs):
    """
    Refresh materialized view and invalidate tile cache when a collection's
    public status changes.
    """
    update_fields = kwargs.get("update_fields")
    if update_fields is None or "public" in update_fields:
        transaction.on_commit(refresh_tiles)


@receiver(post_save, sender=Source)
def refresh_view_on_source_save(sender, instance, **kwargs):
    """
    Refresh materialized view and invalidate tile cache when a source's
    public status changes.
    """
    update_fields = kwargs.get("update_fields")
    if update_fields is None or "public" in update_fields:
        transaction.on_commit(refresh_tiles)


@receiver(post_save, sender=Image)
def queue_image_processing(sender, instance, **kwargs):
    """
    Queue image processing (thumbnail generation and/or transforms) on every save.

    The task itself checks current state and only does work that's needed,
    so it's safe to queue on every save.
    """
    from .tasks import process_image

    def _queue():
        try:
            process_image.apply_async(args=[instance.id])
        except Exception as e:
            logger.error(f"Failed to queue image processing for Image {instance.id}: {e}")

    transaction.on_commit(_queue)
