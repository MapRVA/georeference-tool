import logging
from io import BytesIO
from urllib.parse import urlparse

import requests
from celery import shared_task
from PIL import Image as PILImage

from .models import Image
from .utils import R2Uploader, R2UploaderError

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, ignore_result=True)
def process_image(self, image_id: int, quality: int = 85):
    """
    Ensure an image has the correct transformed/plain assets on R2.

    This task is queued on every Image save. It checks the current state and
    does only the work needed:
    - If the image has a transform: apply it, upload full-size + thumbnail
    - If no transform but no thumbnail: generate a plain thumbnail
    - If everything is already correct: do nothing

    A stale-write guard re-checks the DB before writing, so concurrent tasks
    from rapid saves won't clobber each other.
    """
    try:
        image = Image.objects.get(pk=image_id)
    except Image.DoesNotExist:
        return

    # Snapshot current state — used for stale-write guard later
    task_rotation = image.rotation
    task_mirror = image.mirror

    # Determine what work is needed
    needs_transform = image.has_transform and not image.transformed_permalink
    needs_thumbnail = not image.thumbnail
    needs_transform_cleanup = not image.has_transform and image.transformed_permalink

    if not needs_transform and not needs_thumbnail and not needs_transform_cleanup:
        return

    base_key = get_base_key_from_permalink(image.permalink)
    if not base_key:
        logger.error(
            "Could not extract hash from permalink for image %d: %s",
            image_id,
            image.permalink,
        )
        return

    try:
        r2_uploader = R2Uploader()

        # Download the original image
        pil_image = download_image(image.permalink)
        if pil_image is None:
            raise Exception(f"Failed to download image from {image.permalink}")

        if needs_transform or needs_transform_cleanup:
            # Full reprocessing: either applying new transforms or cleaning up old ones
            if image.has_transform:
                transformed = transform_image(pil_image, image.rotation, image.mirror)

                # Upload full-size transformed image
                transformed_bytes = BytesIO()
                transformed.save(transformed_bytes, "WEBP", quality=quality)
                transformed_bytes.seek(0)

                transformed_key = f"{base_key}_transformed"
                transformed_url = r2_uploader.upload_file_content(
                    transformed_bytes.read(),
                    transformed_key,
                    content_type="image/webp",
                    overwrite=True,
                )

                # Thumbnail from the transformed image
                thumb = create_thumbnail(transformed)
                thumb_bytes = BytesIO()
                thumb.save(thumb_bytes, "WEBP", quality=quality)
                thumb_bytes.seek(0)

                thumb_key = f"{base_key}_transformed_thumb"
                thumb_url = r2_uploader.upload_file_content(
                    thumb_bytes.read(),
                    thumb_key,
                    content_type="image/webp",
                    overwrite=True,
                )

                if _transform_changed(image_id, task_rotation, task_mirror):
                    return

                Image.objects.filter(pk=image_id).update(
                    transformed_permalink=transformed_url,
                    thumbnail=thumb_url,
                )
            else:
                # Transforms removed — generate plain thumbnail, clear transformed_permalink
                thumb = create_thumbnail(pil_image)
                thumb_bytes = BytesIO()
                thumb.save(thumb_bytes, "WEBP", quality=quality)
                thumb_bytes.seek(0)

                thumb_key = f"{base_key}_thumb"
                thumb_url = r2_uploader.upload_file_content(
                    thumb_bytes.read(),
                    thumb_key,
                    content_type="image/webp",
                    overwrite=True,
                )

                if _transform_changed(image_id, task_rotation, task_mirror):
                    return

                Image.objects.filter(pk=image_id).update(
                    transformed_permalink=None,
                    thumbnail=thumb_url,
                )
        else:
            # Just needs a plain thumbnail (no transform involved)
            thumb = create_thumbnail(pil_image)
            thumb_bytes = BytesIO()
            thumb.save(thumb_bytes, "WEBP", quality=quality)
            thumb_bytes.seek(0)

            thumb_key = f"{base_key}_thumb"
            thumb_url = r2_uploader.upload_file_content(
                thumb_bytes.read(),
                thumb_key,
                content_type="image/webp",
                overwrite=True,
            )

            if _transform_changed(image_id, task_rotation, task_mirror):
                return

            Image.objects.filter(pk=image_id).update(thumbnail=thumb_url)

    except R2UploaderError as e:
        raise self.retry(exc=e)
    except Exception:
        logger.exception("Failed to process image %d", image_id)


def _transform_changed(image_id, expected_rotation, expected_mirror):
    """Check if the transform has changed since the task started."""
    current = Image.objects.only("rotation", "mirror").get(pk=image_id)
    if current.rotation != expected_rotation or current.mirror != expected_mirror:
        logger.info(
            "Transform changed for image %d while task was running, skipping write",
            image_id,
        )
        return True
    return False


@shared_task(ignore_result=True)
def process_images_batch(
    collection_id: int | None = None,
    image_ids: list[int] | None = None,
    quality: int = 85,
):
    """
    Queue image processing for multiple images.

    Args:
        collection_id: Optional collection to filter by
        image_ids: Optional specific image IDs to process
        quality: WEBP quality
    """
    queryset = Image.objects.all()

    if collection_id:
        queryset = queryset.filter(collection_id=collection_id)
    if image_ids:
        queryset = queryset.filter(id__in=image_ids)

    count = 0
    for image_id in queryset.values_list("id", flat=True):
        process_image.delay(image_id, quality=quality)
        count += 1

    return {"queued": count}


def transform_image(img: PILImage.Image, rotation: int, mirror: str) -> PILImage.Image:
    """Apply mirror and rotation transforms to a PIL Image.

    Order of operations: mirror first, then rotate (matching EXIF convention).
    """
    if mirror == "h":
        img = img.transpose(PILImage.FLIP_LEFT_RIGHT)
    elif mirror == "v":
        img = img.transpose(PILImage.FLIP_TOP_BOTTOM)

    if rotation == 90:
        img = img.transpose(PILImage.ROTATE_270)  # PIL rotates counter-clockwise
    elif rotation == 180:
        img = img.transpose(PILImage.ROTATE_180)
    elif rotation == 270:
        img = img.transpose(PILImage.ROTATE_90)

    return img


def get_base_key_from_permalink(permalink: str) -> str | None:
    """Extract the base hash key from a permalink URL."""
    try:
        parsed = urlparse(permalink)
        path_parts = parsed.path.strip("/").split("/")
        if path_parts:
            return path_parts[-1]
    except Exception:
        pass
    return None


def download_image(url: str, timeout: int = 30) -> PILImage.Image | None:
    """Download an image from URL and return PIL Image."""
    try:
        response = requests.get(url, timeout=timeout, stream=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith("image/"):
            return None

        image_data = BytesIO(response.content)
        return PILImage.open(image_data).convert("RGB")
    except Exception:
        return None


def create_thumbnail(img: PILImage.Image, max_dimension: int = 500) -> PILImage.Image:
    """Create a thumbnail with max_dimension longest side, preserving aspect ratio."""
    width, height = img.size

    if max(width, height) <= max_dimension:
        return img.copy()

    if width > height:
        scale_factor = max_dimension / width
    else:
        scale_factor = max_dimension / height

    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)

    return img.resize((new_width, new_height), PILImage.LANCZOS)
