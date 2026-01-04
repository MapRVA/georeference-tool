from django.conf import settings

from .models import SiteSettings


def site_settings(request):
    """
    Context processor to make site settings available globally in all templates
    """
    site_settings_model = SiteSettings.load()
    return {
        "site_title": site_settings_model.site_title,
        "site_subtitle": site_settings_model.site_subtitle,
        "footer_content": site_settings_model.footer_content,
        "protomaps_api_key": settings.PROTOMAPS_API_KEY,
        "osm_style_url": settings.OSM_STYLE_URL,
    }
