from django.urls import path

from . import views

app_name = "directories"

urlpatterns = [
    path("directories/entry/", views.entry_validate, name="entry_validate"),
    path(
        "directories/entry/<uuid:entry_uuid>/",
        views.entry_validate,
        name="entry_validate_specific",
    ),
    path(
        "directories/api/entries/<uuid:entry_uuid>/",
        views.entry_update,
        name="entry_update",
    ),
    path(
        "directories/api/entries/<uuid:entry_uuid>/comment/",
        views.add_entry_comment,
        name="add_entry_comment",
    ),
    path("directories/", views.directory_list, name="directory_list"),
    path("directories/create/", views.directory_create, name="directory_create"),
    path(
        "directories/<slug:slug>/",
        views.directory_view,
        name="directory_view",
    ),
    path(
        "directories/edit/<slug:slug>/",
        views.directory_edit,
        name="directory_edit",
    ),
    path(
        "directories/api/presign/<slug:slug>/",
        views.presign_upload,
        name="presign_upload",
    ),
    path(
        "directories/api/confirm/<slug:slug>/",
        views.confirm_upload,
        name="confirm_upload",
    ),
    path(
        "directories/api/pages/<slug:slug>/reorder/",
        views.reorder_pages,
        name="reorder_pages",
    ),
    path(
        "directories/api/pages/<uuid:page_uuid>/",
        views.delete_page,
        name="delete_page",
    ),
    path(
        "directories/api/pages/<slug:slug>/status/",
        views.page_statuses,
        name="page_statuses",
    ),
    path(
        "directories/api/pages/<uuid:page_uuid>/queue-tiles/",
        views.queue_tiles,
        name="queue_tiles",
    ),
    path(
        "directories/api/<slug:slug>/queue-ocr/",
        views.queue_ocr_remaining,
        name="queue_ocr_remaining",
    ),
    path(
        "directories/pages/<uuid:page_uuid>/ocr/",
        views.page_ocr,
        name="page_ocr",
    ),
    path(
        "directories/api/pages/<uuid:page_uuid>/ocr/",
        views.run_ocr,
        name="run_ocr",
    ),
    path(
        "directories/api/pages/<uuid:page_uuid>/ocr-status/",
        views.ocr_status,
        name="ocr_status",
    ),
    path(
        "directories/api/pages/<uuid:page_uuid>/save-entries/",
        views.save_entries,
        name="save_entries",
    ),
    # IIIF Presentation API v3
    path(
        "directories/<slug:slug>/manifest.json",
        views.iiif_manifest,
        name="iiif_manifest",
    ),
    path(
        "directories/pages/<uuid:page_uuid>/manifest.json",
        views.iiif_page_manifest,
        name="iiif_page_manifest",
    ),
    path(
        "directories/iiif/collection.json",
        views.iiif_collection,
        name="iiif_collection",
    ),
]
