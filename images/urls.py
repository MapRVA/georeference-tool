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
    path("aerials/", views.browse_aerials, name="browse_aerials"),
    # Subject browsing
    path("subjects/", views.browse_subjects, name="browse_subjects"),
    path("subjects/<slug:subject_slug>/", views.subject_detail, name="subject_detail"),
    # Georeferencing interface
    path("georeference/", views.georeference_interface, name="georeference_interface"),
    path(
        "georeference-aerial/<int:image_id>/",
        views.aerial_georeference_interface,
        name="aerial_georeference_interface",
    ),
    # List and detail views
    path("", views.image_list, name="image_list"),
    path("stats/", views.image_stats, name="image_stats"),
    path("search/", views.search_page, name="search_page"),
    path("random/", views.get_random_image, name="random_image"),
    # API endpoints for georeferencing (must come before generic <int:image_id>/)
    path(
        "<int:image_id>/georeference/",
        views.georeference_image,
        name="georeference_image",
    ),
    path(
        "<int:image_id>/georeference-aerial/",
        views.aerial_georeference_image,
        name="aerial_georeference_image",
    ),
    path(
        "<int:image_id>/similar/", views.find_similar_images, name="find_similar_images"
    ),
    path(
        "<int:image_id>/add-comment/",
        views.add_comment,
        name="add_comment",
    ),
    path(
        "<int:image_id>/rate/",
        views.submit_rating,
        name="submit_rating",
    ),
    path("<int:image_id>/skip/", views.skip_image, name="skip_image"),
    path(
        "georeference/<int:georeference_id>/validate/",
        views.validate_georeference,
        name="validate_georeference",
    ),
    # Generic image detail view (must come last)
    path("<int:image_id>/", views.image_detail, name="image_detail"),
    # Image management endpoints
    path("<int:image_id>/difficulty/", views.mark_difficulty, name="mark_difficulty"),
    path("<int:image_id>/scale/", views.mark_scale, name="mark_scale"),
    path(
        "<int:image_id>/will-not-georef/",
        views.mark_will_not_georef,
        name="mark_will_not_georef",
    ),
    path(
        "<int:image_id>/aerial/",
        views.mark_aerial,
        name="mark_aerial",
    ),
    path("admin/label-scales/", views.label_scales, name="label_scales"),
    path("admin/update-scale/", views.update_image_scale, name="update_image_scale"),
    # Subject management endpoints
    path(
        "<int:image_id>/subjects/add/",
        views.add_subject_to_image,
        name="add_subject_to_image",
    ),
    path(
        "subjects/mapping/<int:subject_mapping_id>/remove/",
        views.remove_subject_from_image,
        name="remove_subject_from_image",
    ),
    path(
        "image/<int:image_id>/subjects/reorder/",
        views.reorder_subjects,
        name="reorder_subjects",
    ),
    # Public API endpoints
    path("api/v1/geojson/", views.geojson_endpoint, name="geojson"),
    path(
        "api/v1/geojson/aerial/", views.aerial_geojson_endpoint, name="aerial_geojson"
    ),
    path(
        "api/v1/aerials/at-point/",
        views.aerial_georeferences_at_point,
        name="aerial_at_point",
    ),
    path(
        "api/v1/tiles/<int:z>/<int:x>/<int:y>.mvt",
        views.vector_tiles_endpoint,
        name="vector_tiles",
    ),
    path("api/v1/map-layers/", views.map_layers_view, name="map_layers"),
    path("api/v1/search/", views.semantic_search, name="semantic_search"),
    path("api/v1/search/text/", views.text_search, name="text_search"),
    path(
        "api/v1/subjects/autocomplete/",
        views.subject_autocomplete,
        name="subject_autocomplete",
    ),
    # Embeddable map URL
    path("map/embed/", views.map_embed, name="map_embed"),
    # Album management API endpoints
    path("api/v1/user-albums/", views.user_albums_api, name="user_albums_api"),
    path("api/v1/add-to-album/", views.add_image_to_album, name="add_image_to_album"),
    path(
        "api/v1/create-and-add-to-album/",
        views.create_and_add_to_album,
        name="create_and_add_to_album",
    ),
    path(
        "api/v1/remove-from-album/",
        views.remove_image_from_album,
        name="remove_image_from_album",
    ),
    path(
        "album/<uuid:album_id>/toggle-public/",
        views.toggle_album_public,
        name="toggle_album_public",
    ),
    path("album/<uuid:album_id>/edit/", views.edit_album, name="edit_album"),
    path("album/<uuid:album_id>/delete/", views.delete_album, name="delete_album"),
    # Album detail view
    path(
        "user/<str:display_name>/albums/<uuid:album_id>/",
        views.album_detail,
        name="album_detail",
    ),
]
