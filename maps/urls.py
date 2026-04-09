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
]
