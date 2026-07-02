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
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import (
    AerialGeoreference,
    Collection,
    CollectionStats,
    Georeference,
    Image,
    Source,
)
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


# ---------------------------------------------------------------------------
# CollectionStats maintenance
#
# Keep the denormalized per-collection statistics current the moment the
# underlying data changes, so browse pages always show correct numbers
# without running aggregate queries. Refreshes run on_commit, after the
# write is visible to other transactions.
# ---------------------------------------------------------------------------

# Image fields that affect CollectionStats counts. Saves restricted (via
# update_fields) to other fields skip the refresh.
STATS_RELEVANT_IMAGE_FIELDS = {
    "collection",
    "will_not_georef",
    "duplicate_of",
    "aerial",
}


def _refresh_stats_on_commit(collection_ids):
    ids = [cid for cid in collection_ids if cid is not None]
    if not ids:
        return

    def _refresh():
        # Log but don't raise: the triggering write already committed, and a
        # failed refresh only means stale stats until the next event or the
        # periodic reconcile
        try:
            CollectionStats.refresh_for(ids)
        except Exception:
            logger.warning(
                f"Failed to refresh collection stats for {ids}", exc_info=True
            )

    transaction.on_commit(_refresh)


def _collection_id_of_image(image_id):
    return (
        Image.objects.filter(pk=image_id)
        .values_list("collection_id", flat=True)
        .first()
    )


@receiver(post_save, sender=Georeference)
@receiver(post_delete, sender=Georeference)
@receiver(post_save, sender=AerialGeoreference)
@receiver(post_delete, sender=AerialGeoreference)
def refresh_stats_on_georeference_change(sender, instance, **kwargs):
    """Refresh the image's collection stats when a georeference changes.

    On cascade deletes triggered by an Image delete the image row may already
    be gone; the Image post_delete handler covers the refresh in that case.
    """
    _refresh_stats_on_commit([_collection_id_of_image(instance.image_id)])


@receiver(pre_save, sender=Image)
def capture_previous_collection(sender, instance, **kwargs):
    """Remember the collection an image is moving away from, so its stats
    can be refreshed too."""
    instance._previous_collection_id = None
    update_fields = kwargs.get("update_fields")
    if instance.pk and (update_fields is None or "collection" in update_fields):
        instance._previous_collection_id = _collection_id_of_image(instance.pk)


@receiver(post_save, sender=Image)
def refresh_stats_on_image_save(sender, instance, **kwargs):
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not (
        STATS_RELEVANT_IMAGE_FIELDS & set(update_fields)
    ):
        return
    previous = getattr(instance, "_previous_collection_id", None)
    ids = {instance.collection_id}
    if previous and previous != instance.collection_id:
        ids.add(previous)
    _refresh_stats_on_commit(ids)


@receiver(post_delete, sender=Image)
def refresh_stats_on_image_delete(sender, instance, **kwargs):
    _refresh_stats_on_commit([instance.collection_id])


@receiver(post_save, sender=Collection)
def seed_stats_on_collection_create(sender, instance, created, **kwargs):
    """Give every new collection a (zeroed) stats row immediately."""
    if created:
        _refresh_stats_on_commit([instance.pk])


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
            logger.error(
                f"Failed to queue image processing for Image {instance.id}: {e}"
            )

    transaction.on_commit(_queue)
