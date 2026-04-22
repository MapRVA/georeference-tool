import logging
import mimetypes

import requests
from celery import shared_task
from django.contrib.auth.models import User

from images.utils import R2Uploader, R2UploaderError

from .models import UserProfile

logger = logging.getLogger(__name__)

AVATAR_CACHE_CONTROL = "public, max-age=3600"
AVATAR_DOWNLOAD_TIMEOUT = 30


@shared_task(bind=True, max_retries=3, default_retry_delay=60, ignore_result=True)
def download_osm_avatar(self, user_id: int, source_url: str):
    """Fetch an OSM profile picture, mirror it to R2, and save the URL."""
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return

    try:
        response = requests.get(
            source_url,
            timeout=AVATAR_DOWNLOAD_TIMEOUT,
            headers={"User-Agent": "Yesterdays/1.0 (https://maprva.org)"},
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise self.retry(exc=e)

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    extension = mimetypes.guess_extension(content_type) if content_type else None
    if not extension:
        extension = ".jpg"

    key = f"users/{user.pk}/profile{extension}"

    try:
        public_url = R2Uploader().upload_file_content(
            response.content,
            key,
            content_type=content_type or None,
            overwrite=True,
            cache_control=AVATAR_CACHE_CONTROL,
        )
    except R2UploaderError as e:
        raise self.retry(exc=e)

    UserProfile.objects.update_or_create(
        user=user,
        defaults={"profile_picture_url": public_url},
    )
