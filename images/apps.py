from django.apps import AppConfig


class ImagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "images"
    verbose_name = "Image Georeferencing"

    def ready(self):
        """Import signal handlers when the app is ready."""
        import images.signals  # noqa: F401
