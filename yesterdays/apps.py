import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class YesterdaysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "yesterdays"

    def ready(self):
        if getattr(settings, "PROMETHEUS_ENABLED", False):
            self._start_metrics_server()

        if getattr(settings, "CLIP_WARMUP_ENABLED", False):
            self._warmup_clip_model()

    def _warmup_clip_model(self):
        from images.tasks import warmup_clip_model

        warmup_clip_model()

    def _start_metrics_server(self, port=9090, addr="0.0.0.0"):
        from prometheus_client import start_http_server

        try:
            start_http_server(port, addr=addr)
            logger.info(f"Prometheus metrics server started on {addr}:{port}")
        except OSError as e:
            if "Address already in use" in str(e):
                logger.debug(f"Metrics server already running on port {port}")
            else:
                logger.error(f"Failed to start metrics server: {e}")
