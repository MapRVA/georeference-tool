from io import BytesIO
from urllib.parse import urlparse

import requests
from celery import shared_task
from PIL import Image as PILImage

from .models import Image
from .utils import R2Uploader, R2UploaderError


@shared_task(bind=True, max_retries=3, default_retry_delay=60, ignore_result=True)
def generate_thumbnail_for_image(
    self, image_id: int, quality: int = 85, overwrite: bool = False
):
    """
    Generate a thumbnail for a single image and upload to R2.

    Args:
        image_id: The database ID of the Image to process
        quality: WEBP quality (1-100)
        overwrite: Whether to overwrite existing thumbnail

    Returns:
        dict with status and thumbnail_url or error message
    """
    try:
        image = Image.objects.get(pk=image_id)
    except Image.DoesNotExist:
        return {"status": "error", "message": f"Image {image_id} not found"}

    # Skip if thumbnail already exists (unless overwrite)
    if image.thumbnail and not overwrite:
        return {
            "status": "skipped",
            "message": "Thumbnail already exists",
            "thumbnail_url": image.thumbnail,
        }

    # Extract thumbnail key from permalink
    thumbnail_key = get_thumbnail_key_from_permalink(image.permalink)
    if not thumbnail_key:
        return {
            "status": "error",
            "message": f"Could not extract hash from permalink: {image.permalink}",
        }

    try:
        # Initialize R2 uploader
        r2_uploader = R2Uploader()

        # Download the source image
        pil_image = download_image(image.permalink)
        if pil_image is None:
            raise Exception(f"Failed to download image from {image.permalink}")

        # Generate thumbnail
        thumbnail = create_thumbnail(pil_image)

        # Convert to bytes
        thumbnail_bytes = BytesIO()
        thumbnail.save(thumbnail_bytes, "WEBP", quality=quality)
        thumbnail_bytes.seek(0)

        # Upload to R2
        public_url = r2_uploader.upload_file_content(
            thumbnail_bytes.read(),
            thumbnail_key,
            content_type="image/webp",
            overwrite=overwrite,
        )

        # Update the Image model
        image.thumbnail = public_url
        image.save(update_fields=["thumbnail"])

        return {"status": "success", "thumbnail_url": public_url}

    except R2UploaderError as e:
        # Retry on R2 errors
        raise self.retry(exc=e)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@shared_task(ignore_result=True)
def generate_thumbnails_batch(
    collection_id: int | None = None,
    image_ids: list[int] | None = None,
    quality: int = 85,
    overwrite: bool = False,
):
    """
    Queue thumbnail generation for multiple images.

    Args:
        collection_id: Optional collection to filter by
        image_ids: Optional specific image IDs to process
        quality: WEBP quality
        overwrite: Whether to regenerate existing thumbnails
    """
    queryset = Image.objects.all()

    if collection_id:
        queryset = queryset.filter(collection_id=collection_id)
    if image_ids:
        queryset = queryset.filter(id__in=image_ids)
    if not overwrite:
        queryset = queryset.filter(thumbnail__isnull=True)

    count = 0
    for image_id in queryset.values_list("id", flat=True):
        generate_thumbnail_for_image.delay(
            image_id, quality=quality, overwrite=overwrite
        )
        count += 1

    return {"queued": count}


def get_thumbnail_key_from_permalink(permalink: str) -> str | None:
    """Extract hash from permalink and generate thumbnail key."""
    try:
        parsed = urlparse(permalink)
        path_parts = parsed.path.strip("/").split("/")
        if path_parts:
            hash_value = path_parts[-1]
            return f"{hash_value}_thumb"
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

    if width > height:
        scale_factor = max_dimension / width
    else:
        scale_factor = max_dimension / height

    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)

    return img.resize((new_width, new_height), PILImage.LANCZOS)
