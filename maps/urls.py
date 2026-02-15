from django.urls import path

from . import views

app_name = "maps"

urlpatterns = [
    path("", views.browse_maps, name="browse_maps"),
    path(
        "<slug:collection_slug>/<slug:layer_slug>/",
        views.layer_detail,
        name="layer_detail",
    ),
    path("api/v1/map-layers/", views.map_layers_view, name="map_layers"),
]
