from django.urls import path
from . import views

app_name = "images"

urlpatterns = [
    # Browse interface
    path("browse/", views.browse_sources, name="browse_sources"),
    path("browse/<slug:slug>/", views.source_detail, name="source_detail"),
    path(
        "browse/<slug:source_slug>/<slug:collection_slug>/",
        views.collection_detail,
        name="collection_detail",
    ),
    # Georeferencing interface
    path("georeference/", views.georeference_interface, name="georeference_interface"),
    # List and detail views
    path("", views.image_list, name="image_list"),
    path("<int:image_id>/", views.image_detail, name="image_detail"),
    path("stats/", views.image_stats, name="image_stats"),
    path("random/", views.get_random_image, name="random_image"),
    # API endpoints for georeferencing
    path(
        "<int:image_id>/georeference/",
        views.georeference_image,
        name="georeference_image",
    ),
    path(
        "georeference/<int:georeference_id>/validate/",
        views.validate_georeference,
        name="validate_georeference",
    ),
    path("<int:image_id>/skip/", views.skip_image, name="skip_image"),
    # Image management endpoints
    path("<int:image_id>/difficulty/", views.mark_difficulty, name="mark_difficulty"),
    path(
        "<int:image_id>/will-not-georef/",
        views.mark_will_not_georef,
        name="mark_will_not_georef",
    ),
    # GeoJSON endpoint
    path("geojson/", views.geojson_endpoint, name="geojson"),
]
