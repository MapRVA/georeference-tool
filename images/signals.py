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

from images.models import Image

from .models import Collection, Georeference, Source

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


@receiver(post_save, sender=Image)
def queue_thumbnail_generation(sender, instance, created, **kwargs):
    """
    Queue thumbnail generation when a new Image is created.

    This signal handler triggers when an Image instance is saved.
    It only queues the thumbnail generation task for newly created images
    that don't already have a thumbnail.

    Args:
        sender: The model class that sent the signal (Image)
        instance: The actual instance of the model that was saved
        created: Boolean indicating if this is a new instance
        **kwargs: Additional keyword arguments from the signal
    """
    # Debug logging
    logger.info(f"Signal triggered for Image {instance.id}, created={created}")

    # Only process newly created images
    if not created:
        logger.info(f"Image {instance.id} is not new, skipping")
        return

    # Skip if thumbnail already exists
    if instance.thumbnail:
        logger.info(f"Image {instance.id} already has thumbnail, skipping generation")
        return

    logger.info(f"Processing new Image {instance.id} for thumbnail generation")

    # Import here to avoid circular imports
    from yesterdays.tasks import generate_thumbnail_for_image

    # Queue the thumbnail generation task
    try:
        # Use a small delay to ensure the database transaction is committed
        # before the Celery worker tries to fetch the image
        task = generate_thumbnail_for_image.apply_async(
            args=[instance.id],
            countdown=5,  # Wait 5 seconds before starting
            queue="background",  # Use background queue for thumbnail generation
        )
        logger.info(
            f"Queued thumbnail generation for Image {instance.id}, task ID: {task.id}"
        )
    except Exception as e:
        logger.error(
            f"Failed to queue thumbnail generation for Image {instance.id}: {e}"
        )
