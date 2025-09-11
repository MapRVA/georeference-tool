from django.apps import AppConfig


class OsmAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "osm_auth"

    def ready(self):
        # Import models to ensure User.get_display_name method is added
        from . import models
