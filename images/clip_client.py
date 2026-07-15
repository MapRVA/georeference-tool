"""
HTTP client for the CLIP embedding microservice (services/clip).

Callers should treat requests exceptions like any other embedding failure;
the search views already wrap embedding calls accordingly.
"""

import requests
from django.conf import settings

_session = requests.Session()


def is_configured():
    return bool(settings.CLIP_SERVICE_URL)


def get_text_embedding(text):
    """
    Encode text into a normalized 768-dim CLIP embedding (list of floats).
    """
    response = _session.post(
        f"{settings.CLIP_SERVICE_URL}/embed/text",
        json={"text": text},
        timeout=settings.CLIP_SERVICE_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def get_image_embedding(image_bytes):
    """
    Encode image bytes into a normalized 768-dim CLIP embedding.
    """
    response = _session.post(
        f"{settings.CLIP_SERVICE_URL}/embed/image",
        data=image_bytes,
        headers={"Content-Type": "application/octet-stream"},
        timeout=settings.CLIP_SERVICE_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["embedding"]
