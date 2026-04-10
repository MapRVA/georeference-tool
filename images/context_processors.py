import json

from django.conf import settings

from maps.models import LayerCollection, MapLayer

from .models import SiteSettings
from .views import get_tile_version


def _build_map_layers_data():
    """Build the map layers JSON for the frontend layer control."""
    primary_layers = []
    for layer in MapLayer.objects.filter(collection__isnull=True).order_by("order"):
        layer_data = {
            "slug": layer.slug,
            "name": layer.name,
            "type": layer.type,
            "url": layer.url,
            "is_default": layer.is_default,
        }
        if layer.attribution:
            layer_data["attribution"] = layer.attribution
        primary_layers.append(layer_data)

    collections_data = []
    for collection in LayerCollection.objects.prefetch_related("layers").all():
        collection_data = {
            "name": collection.name,
            "description": collection.description,
            "layers": [],
        }
        for layer in collection.layers.all():
            layer_data = {
                "name": layer.name,
                "type": layer.type,
                "url": layer.url,
            }
            if layer.attribution:
                layer_data["attribution"] = layer.attribution
            if layer.description:
                layer_data["description"] = layer.description
            collection_data["layers"].append(layer_data)
        collections_data.append(collection_data)

    return {
        "primary_layers": primary_layers,
        "collections": collections_data,
    }


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
        "default_map_center": [
            site_settings_model.default_map_longitude,
            site_settings_model.default_map_latitude,
        ],
        "default_map_zoom": site_settings_model.default_map_zoom,
        "admin_email": site_settings_model.admin_email,
        "tile_version": get_tile_version(),
        "DIRECTORIES_ENABLED": settings.DIRECTORIES_ENABLED,
        "map_layers_json": json.dumps(_build_map_layers_data()),
    }
