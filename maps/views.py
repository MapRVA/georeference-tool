import os

from django.db.models import Prefetch
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


