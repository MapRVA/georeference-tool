from django.apps import AppConfig


class ActivityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "activity"
    verbose_name = "Activity Feed"

    def ready(self):
        """Import signal handlers when the app is ready."""
        import activity.signals  # noqa: F401
