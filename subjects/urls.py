from django.urls import path

from . import views

app_name = "subjects"

urlpatterns = [
    # Subject browsing
    path("", views.browse_subjects, name="browse_subjects"),
    path("<slug:subject_slug>/", views.subject_detail, name="subject_detail"),
    path(
        "<slug:subject_slug>/similar/",
        views.find_similar_images_to_subject,
        name="subject_similar_images",
    ),
    # API endpoints
    path(
        "api/autocomplete/",
        views.subject_autocomplete,
        name="subject_autocomplete",
    ),
    path(
        "api/wikidata-lookup/",
        views.wikidata_lookup,
        name="wikidata_lookup",
    ),
    path("api/all/", views.all_subjects_api, name="all_subjects_api"),
    path(
        "api/bulk-add/",
        views.bulk_add_subject_to_images,
        name="bulk_add_subject_to_images",
    ),
    path(
        "api/image/<int:image_id>/add/",
        views.add_subject_to_image,
        name="add_subject_to_image",
    ),
    path(
        "api/mapping/<int:subject_mapping_id>/remove/",
        views.remove_subject_from_image,
        name="remove_subject_from_image",
    ),
    path(
        "api/image/<int:image_id>/reorder/",
        views.reorder_subjects,
        name="reorder_subjects",
    ),
]
