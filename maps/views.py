import os

from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from images.utils import render_markdown_safe

from .models import LayerCollection, MapLayer


def browse_maps(request):
    """Display all map layers organized by collections."""
    collections = LayerCollection.objects.prefetch_related(
        Prefetch("layers", queryset=MapLayer.objects.order_by("order"))
    ).order_by("order")
    # Render markdown for collection descriptions and layer descriptions
    collections_with_rendered = []
    for collection in collections:
        rendered_description = None
        if collection.description:
            rendered_description = render_markdown_safe(collection.description)

        # Render markdown for each layer description
        layers_with_rendered = []
        for layer in collection.layers.all():
            rendered_layer_description = None
            if layer.description:
                rendered_layer_description = render_markdown_safe(layer.description)
            layers_with_rendered.append(
                {"layer": layer, "rendered_description": rendered_layer_description}
            )

        collections_with_rendered.append(
            {
                "collection": collection,
                "rendered_description": rendered_description,
                "layers": layers_with_rendered,
            }
        )
    return render(
        request, "maps/browse_maps.html", {"collections": collections_with_rendered}
    )


def layer_detail(request, collection_slug, layer_slug):
    """Display a single map layer."""
    layer = get_object_or_404(
        MapLayer, collection__slug=collection_slug, slug=layer_slug
    )

    # Render markdown for layer description
    rendered_description = None
    if layer.description:
        rendered_description = render_markdown_safe(layer.description)

    context = {
        "layer": layer,
        "rendered_description": rendered_description,
        "protomaps_api_key": os.environ.get("PROTOMAPS_API_KEY", ""),
    }
    return render(request, "maps/map_detail.html", context)


def map_layers_view(request):
    """Return all map layers organized by collections in a single object"""
    collections = LayerCollection.objects.prefetch_related("layers").all()
    collections_data = []
    for collection in collections:
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
            # Add optional fields if they exist
            if layer.attribution:
                layer_data["attribution"] = layer.attribution
            if layer.description:
                layer_data["description"] = layer.description
            collection_data["layers"].append(layer_data)
        collections_data.append(collection_data)
    # Return single object with all metadata
    response_data = {"collections": collections_data}
    return JsonResponse(response_data)
