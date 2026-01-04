from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404

from .models import LayerCollection, MapLayer


def browse_maps(request):
    """Display all map layers organized by collections."""
    collections = LayerCollection.objects.prefetch_related(
        Prefetch("layers", queryset=MapLayer.objects.order_by("order"))
    ).order_by("order")
    return render(request, "maps/browse_maps.html", {"collections": collections})


def layer_detail(request, collection_slug, layer_slug):
    """Display a single map layer."""
    layer = get_object_or_404(MapLayer, collection__slug=collection_slug, slug=layer_slug)
    return render(request, "maps/map_detail.html", {"layer": layer})


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
