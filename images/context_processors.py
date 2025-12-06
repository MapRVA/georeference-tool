from .models import SiteSettings


def site_settings(request):
    """
    Context processor to make site settings available globally in all templates
    """
    settings = SiteSettings.load()
    return {
        'site_title': settings.site_title,
        'site_subtitle': settings.site_subtitle,
        'footer_content': settings.footer_content,
    }
