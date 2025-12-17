import json

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    Collection,
    Georeference,
    GeoreferenceValidation,
    Image,
    ImageSkip,
    LayerCollection,
    MapLayer,
    PreCollection,
    PreImage,
    SiteSettings,
    Source,
    Subject,
    SubjectMapping,
    WikidataItem,
)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "public", "url", "created_at", "collection_count")
    list_filter = ("public", "created_at")
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")

    def collection_count(self, obj):
        return obj.collections.count()

    collection_count.short_description = "Collections"


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "source",
        "public",
        "url",
        "created_at",
        "image_count",
        "label_collection_button",
    )
    list_filter = ("public", "source", "created_at")
    search_fields = ("name", "description", "source__name")
    readonly_fields = ("created_at", "updated_at")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:collection_id>/label/",
                self.admin_site.admin_view(self.label_collection),
                name="images_collection_label",
            ),
            path(
                "<int:collection_id>/label/update/",
                self.admin_site.admin_view(self.update_image_label),
                name="images_collection_update_label",
            ),
        ]
        return custom_urls + urls

    def image_count(self, obj):
        return obj.images.count()

    image_count.short_description = "Images"

    def label_collection_button(self, obj):
        url = reverse("admin:images_collection_label", args=[obj.pk])
        return format_html('<a class="button" href="{}">Label Collection</a>', url)

    label_collection_button.short_description = "Actions"

    def label_collection(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        images = collection.images.filter(duplicate_of__isnull=True).order_by("id")

        # Count duplicates
        total_images = collection.images.count()
        duplicate_count = total_images - images.count()

        # Serialize image data for JavaScript
        image_data = []
        for image in images:
            image_data.append(
                {
                    "id": image.id,
                    "title": image.title,
                    "permalink": image.permalink,
                    "description": image.description,
                    "date_display": image.date_display,
                    "difficulty": image.difficulty,
                    "scale": image.scale,
                    "will_not_georef": image.will_not_georef,
                    "absolute_url": image.get_absolute_url(),
                }
            )

        context = {
            "collection": collection,
            "images": images,
            "image_data_json": json.dumps(image_data),
            "title": f"Label Collection: {collection.name}",
            "duplicate_count": duplicate_count,
        }

        return render(request, "admin/images/collection_label.html", context)

    def update_image_label(self, request, collection_id):
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=400)

        image_id = request.POST.get("image_id")
        difficulty = request.POST.get("difficulty")
        scale = request.POST.get("scale")
        will_not_georef = request.POST.get("will_not_georef") == "true"

        try:
            image = get_object_or_404(
                Image,
                id=image_id,
                collection_id=collection_id,
                duplicate_of__isnull=True,
            )

            if difficulty and difficulty != "none":
                image.difficulty = difficulty
            elif difficulty == "none":
                image.difficulty = None

            if scale and scale.isdigit():
                image.scale = int(scale)
            elif scale == "none":
                image.scale = None

            image.will_not_georef = will_not_georef
            image.save(update_fields=["difficulty", "scale", "will_not_georef"])

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)


@admin.register(PreCollection)
class PreCollectionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "source",
        "complete",
        "url",
        "created_at",
        "image_count",
        "reviewed_count",
        "label_precollection_button",
    )
    list_filter = ("complete", "source", "created_at")
    search_fields = ("name", "description", "source__name")
    readonly_fields = ("created_at", "updated_at")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:precollection_id>/label/",
                self.admin_site.admin_view(self.label_precollection),
                name="images_precollection_label",
            ),
            path(
                "<int:precollection_id>/label/update/",
                self.admin_site.admin_view(self.update_preimage_label),
                name="images_precollection_update_label",
            ),
            path(
                "<int:precollection_id>/mark-complete/",
                self.admin_site.admin_view(self.mark_complete),
                name="images_precollection_mark_complete",
            ),
        ]
        return custom_urls + urls

    def image_count(self, obj):
        return obj.images.count()

    image_count.short_description = "Images"

    def reviewed_count(self, obj):
        return obj.images.filter(keep__isnull=False).count()

    reviewed_count.short_description = "Reviewed"

    def label_precollection_button(self, obj):
        if obj.complete:
            return format_html(
                '<span style="color: #28a745; font-weight: bold;">✓ Complete</span>'
            )
        else:
            url = reverse("admin:images_precollection_label", args=[obj.pk])
            return format_html('<a class="button" href="{}">Review Images</a>', url)

    label_precollection_button.short_description = "Actions"

    def label_precollection(self, request, precollection_id):
        precollection = get_object_or_404(PreCollection, id=precollection_id)
        # Exclude images that have already been imported
        images = precollection.images.filter(imported=False).order_by("id")

        # Calculate counts
        reviewed_count = images.filter(keep__isnull=False).count()
        keep_count = images.filter(keep=True).count()
        discard_count = images.filter(keep=False).count()

        # Serialize image data for JavaScript
        image_data = []
        for image in images:
            image_data.append(
                {
                    "id": image.id,
                    "title": image.title,
                    "permalink": image.permalink,
                    "description": image.description,
                    "date_display": image.date_display,
                    "keep": image.keep,
                    "absolute_url": image.get_absolute_url(),
                }
            )

        context = {
            "precollection": precollection,
            "images": images,
            "reviewed_count": reviewed_count,
            "keep_count": keep_count,
            "discard_count": discard_count,
            "image_data_json": json.dumps(image_data),
            "title": f"Review Pre-Collection: {precollection.name}",
        }

        return render(request, "admin/images/precollection_label.html", context)

    def update_preimage_label(self, request, precollection_id):
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=400)

        image_id = request.POST.get("image_id")
        keep_value = request.POST.get("keep")

        try:
            image = get_object_or_404(
                PreImage, id=image_id, collection_id=precollection_id
            )

            if keep_value == "null":
                image.keep = None
            elif keep_value == "true":
                image.keep = True
            elif keep_value == "false":
                image.keep = False
            else:
                return JsonResponse({"error": "Invalid keep value"}, status=400)

            image.save(update_fields=["keep"])

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def mark_complete(self, request, precollection_id):
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=400)

        try:
            precollection = get_object_or_404(PreCollection, id=precollection_id)
            precollection.complete = True
            precollection.full_clean()  # This will trigger validation
            precollection.save(update_fields=["complete"])

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)


@admin.register(PreImage)
class PreImageAdmin(admin.ModelAdmin):
    list_display = (
        "title_or_id",
        "collection",
        "date_display",
        "edtf_date",
        "keep",
    )
    list_filter = ("keep", "collection__source")
    search_fields = ("title", "description", "collection__name")
    readonly_fields = ("created_at", "updated_at")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Make nullable fields not required in admin form
        nullable_fields = [
            "description",
            "license_title",
            "license_permalink",
            "creator",
            "ref",
            "original_date",
            "edtf_date",
            "keep",
        ]
        for field_name in nullable_fields:
            if field_name in form.base_fields:
                form.base_fields[field_name].required = False
        return form

    def save_model(self, request, obj, form, change):
        # Convert empty strings to None for nullable fields
        nullable_fields = [
            "description",
            "license_title",
            "license_permalink",
            "creator",
            "ref",
            "original_date",
            "edtf_date",
        ]
        for field_name in nullable_fields:
            if hasattr(obj, field_name) and getattr(obj, field_name) == "":
                setattr(obj, field_name, None)
        super().save_model(request, obj, form, change)

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "collection",
                    "title",
                    "creator",
                    "permalink",
                    "description",
                    "ref",
                )
            },
        ),
        (
            "License Information",
            {"fields": ("license_title", "license_permalink")},
        ),
        (
            "Date Information",
            {
                "fields": ("original_date", "edtf_date"),
                "description": "Leave fields blank if date information is not available",
            },
        ),
        (
            "Review",
            {
                "fields": ("keep",),
                "description": "Whether to keep this image for the main collection",
            },
        ),
        (
            "System Information",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def title_or_id(self, obj):
        return obj.title if obj.title else f"PreImage {obj.id}"

    title_or_id.short_description = "Title/ID"


@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = (
        "title_or_id",
        "collection",
        "date_display",
        "edtf_date",
        "difficulty",
        "scale",
        "will_not_georef",
        "skip_count",
        "georeference_status",
    )
    list_filter = ("difficulty", "scale", "will_not_georef", "collection__source")
    search_fields = ("title", "description", "collection__name")
    readonly_fields = ("created_at", "updated_at", "skip_count")
    autocomplete_fields = ["duplicate_of"]
    actions = ["label_scales_action"]

    def label_scales_action(self, request, queryset):
        return HttpResponseRedirect(reverse("images:label_scales"))

    label_scales_action.short_description = "Label Image Scales"

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Make nullable fields not required in admin form
        nullable_fields = [
            "original_url",
            "description",
            "license_title",
            "license_permalink",
            "creator",
            "ref",
            "original_date",
            "edtf_date",
            "difficulty",
            "scale",
        ]
        for field_name in nullable_fields:
            if field_name in form.base_fields:
                form.base_fields[field_name].required = False

        # Remove add, change, delete buttons for duplicate_of field
        if "duplicate_of" in form.base_fields:
            form.base_fields["duplicate_of"].widget.can_add_related = False
            form.base_fields["duplicate_of"].widget.can_change_related = False
            form.base_fields["duplicate_of"].widget.can_delete_related = False

        return form

    def get_search_results(self, request, queryset, search_term):
        if search_term:
            try:
                # If search term is a number, only return exact ID match
                image_id = int(search_term)
                queryset = self.model.objects.filter(id=image_id)
                use_distinct = False
            except (ValueError, TypeError):
                # If not a number, use normal fuzzy search
                queryset, use_distinct = super().get_search_results(
                    request, queryset, search_term
                )
        else:
            queryset, use_distinct = super().get_search_results(
                request, queryset, search_term
            )
        return queryset, use_distinct

    def save_model(self, request, obj, form, change):
        # Convert empty strings to None for nullable fields
        nullable_fields = [
            "original_url",
            "description",
            "license_title",
            "license_permalink",
            "creator",
            "ref",
            "original_date",
            "edtf_date",
            "difficulty",
            "scale",
        ]
        for field_name in nullable_fields:
            if hasattr(obj, field_name) and getattr(obj, field_name) == "":
                setattr(obj, field_name, None)
        super().save_model(request, obj, form, change)

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "collection",
                    "title",
                    "creator",
                    "permalink",
                    "description",
                    "ref",
                    "original_url",
                    "duplicate_of",
                )
            },
        ),
        (
            "License Information",
            {"fields": ("license_title", "license_permalink")},
        ),
        (
            "Date Information",
            {
                "fields": ("original_date", "edtf_date"),
                "description": "Leave fields blank if date information is not available",
            },
        ),
        ("Georeferencing", {"fields": ("difficulty", "scale", "will_not_georef")}),
        (
            "System Information",
            {
                "fields": ("skip_count", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def title_or_id(self, obj):
        return obj.title if obj.title else f"Image {obj.id}"

    title_or_id.short_description = "Title/ID"

    def georeference_status(self, obj):
        return obj.georeference_status

    georeference_status.short_description = "Status"


@admin.register(Georeference)
class GeoreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "image",
        "point",
        "direction",
        "georeferenced_by",
        "georeferenced_at",
        "validation_count",
    )
    list_filter = ("georeferenced_by", "georeferenced_at")
    search_fields = (
        "image__title",
        "image__collection__name",
        "georeferenced_by__username",
    )
    readonly_fields = ("georeferenced_at", "updated_at", "validation_count")
    autocomplete_fields = ["image"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        # Remove add, change, delete buttons for image field
        if "image" in form.base_fields:
            form.base_fields["image"].widget.can_add_related = False
            form.base_fields["image"].widget.can_change_related = False
            form.base_fields["image"].widget.can_delete_related = False

        # Make georeferenced_by not required to allow anonymous submissions
        if "georeferenced_by" in form.base_fields:
            form.base_fields["georeferenced_by"].required = False

        return form

    fieldsets = (
        ("Image Information", {"fields": ("image",)}),
        ("Coordinates", {"fields": ("point", "direction")}),
        ("Attribution", {"fields": ("georeferenced_by", "confidence_notes")}),
        (
            "System Information",
            {
                "fields": ("georeferenced_at", "updated_at", "validation_count"),
                "classes": ("collapse",),
            },
        ),
    )

    def validation_count(self, obj):
        return obj.validations.count()

    validation_count.short_description = "Validations"


@admin.register(GeoreferenceValidation)
class GeoreferenceValidationAdmin(admin.ModelAdmin):
    list_display = ("georeference", "validation", "validated_by", "validated_at")
    list_filter = ("validation", "validated_by", "validated_at")
    search_fields = ("georeference__image__title", "validated_by__username", "notes")
    readonly_fields = ("validated_at",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("georeference__image", "validated_by")
        )


@admin.register(ImageSkip)
class ImageSkipAdmin(admin.ModelAdmin):
    list_display = ("image", "user", "reason", "skipped_at")
    list_filter = ("user", "skipped_at", "reason")
    search_fields = ("image__title", "user__username", "reason")
    readonly_fields = ("skipped_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("image", "user")


@admin.register(LayerCollection)
class LayerCollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "layer_count", "created_at")
    list_filter = ("created_at",)
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("order", "name")

    def layer_count(self, obj):
        return obj.layers.count()

    layer_count.short_description = "Layers"


@admin.register(MapLayer)
class MapLayerAdmin(admin.ModelAdmin):
    list_display = ("name", "collection", "order", "type", "url", "created_at")
    list_filter = ("type", "collection", "created_at")
    search_fields = ("name", "description", "collection__name")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("collection__order", "collection__name", "order", "name")

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "collection", "order", "description")},
        ),
        ("Map Data", {"fields": ("type", "url", "attribution")}),
        (
            "System Information",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


def refresh_wikidata_info(modeladmin, request, queryset):
    """Admin action to refresh Wikidata information for selected items"""
    updated_count = 0
    failed_count = 0

    for item in queryset:
        if item.populate_from_wikidata():
            updated_count += 1
        else:
            failed_count += 1

    if updated_count > 0:
        modeladmin.message_user(
            request, f"Successfully updated {updated_count} Wikidata item(s)."
        )
    if failed_count > 0:
        modeladmin.message_user(
            request,
            f"Failed to update {failed_count} Wikidata item(s).",
            level="WARNING",
        )


refresh_wikidata_info.short_description = "Refresh Wikidata information"


@admin.register(WikidataItem)
class WikidataItemAdmin(admin.ModelAdmin):
    list_display = (
        "wikidata_id",
        "title",
        "description_truncated",
        "va_landmark_id",
        "inception",
        "last_updated",
    )
    list_filter = ("last_updated", "inception")
    search_fields = ("wikidata_id", "title", "description", "va_landmark_id")
    readonly_fields = ("created_at", "last_updated", "wikidata_url", "refresh_button")
    actions = ["refresh_selected_wikidata_items"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/refresh/",
                self.admin_site.admin_view(self.refresh_individual_item),
                name="images_wikidataitem_refresh",
            ),
        ]
        return custom_urls + urls

    def refresh_individual_item(self, request, object_id):
        """Refresh Wikidata information for a single item"""
        wikidata_item = get_object_or_404(WikidataItem, pk=object_id)

        # Add progress message
        messages.info(
            request,
            f"Refreshing Wikidata information for {wikidata_item.wikidata_id}... This may take a moment.",
        )

        try:
            if wikidata_item.populate_from_wikidata():
                wikidata_item.save()
                messages.success(
                    request,
                    f"✓ Successfully refreshed Wikidata information for {wikidata_item.wikidata_id}. "
                    f"Title: {wikidata_item.title}",
                )
            else:
                messages.warning(
                    request,
                    f"⚠ No data found for {wikidata_item.wikidata_id}. "
                    f"The item may not exist or may not have English labels.",
                )
        except ValidationError as e:
            error_msg = str(e)
            if "Network error" in error_msg:
                messages.error(
                    request,
                    f"🔄 Network error refreshing {wikidata_item.wikidata_id}. "
                    f"The system automatically retried the request. Please try again if this persists.",
                )
            else:
                messages.error(
                    request, f"❌ Error refreshing Wikidata information: {error_msg}"
                )
        except Exception as e:
            messages.error(
                request, f"❌ Unexpected error refreshing Wikidata information: {e}"
            )

        return HttpResponseRedirect(
            reverse("admin:images_wikidataitem_change", args=[object_id])
        )

    def refresh_selected_wikidata_items(self, request, queryset):
        """Refresh Wikidata information for selected items"""
        total_count = queryset.count()
        updated_count = 0
        failed_count = 0
        network_errors = 0
        error_messages = []

        # Add progress message
        self.message_user(
            request,
            f"Refreshing {total_count} Wikidata item(s)... This may take a moment.",
        )

        for item in queryset:
            try:
                if item.populate_from_wikidata():
                    item.save()
                    updated_count += 1
                else:
                    failed_count += 1
            except ValidationError as e:
                failed_count += 1
                error_str = str(e)
                if "Network error" in error_str:
                    network_errors += 1
                error_messages.append(f"{item.wikidata_id}: {error_str}")
            except Exception as e:
                failed_count += 1
                error_messages.append(f"{item.wikidata_id}: Unexpected error - {e}")

        # Provide detailed success/failure feedback
        if updated_count > 0:
            self.message_user(
                request, f"✓ Successfully updated {updated_count} Wikidata item(s)."
            )

        if failed_count > 0:
            error_msg = (
                f"⚠ Failed to update {failed_count} of {total_count} Wikidata item(s)."
            )
            if network_errors > 0:
                error_msg += (
                    f" ({network_errors} network errors - these may succeed if retried)"
                )
            if error_messages and len(error_messages) <= 3:
                error_msg += f" Errors: {'; '.join(error_messages)}"
            elif error_messages:
                error_msg += f" First 3 errors: {'; '.join(error_messages[:3])} (and {len(error_messages) - 3} more)"
            self.message_user(request, error_msg, level=messages.WARNING)

    refresh_selected_wikidata_items.short_description = "Refresh Wikidata information"

    fieldsets = (
        (
            "Wikidata Information",
            {
                "fields": (
                    "wikidata_id",
                    "title",
                    "description",
                    "wikidata_url",
                    "wikipedia_url",
                    "refresh_button",
                )
            },
        ),
        (
            "Additional Metadata",
            {
                "fields": ("va_landmark_id", "architect", "image_url", "inception"),
                "description": "Optional additional information about the subject",
            },
        ),
        (
            "System Information",
            {
                "fields": ("created_at", "last_updated"),
                "classes": ("collapse",),
            },
        ),
    )

    def description_truncated(self, obj):
        if obj.description:
            return (
                obj.description[:100] + "..."
                if len(obj.description) > 100
                else obj.description
            )
        return ""

    description_truncated.short_description = "Description"

    def wikidata_url(self, obj):
        return obj.wikidata_url if obj.wikidata_id else ""

    wikidata_url.short_description = "Wikidata URL"

    def refresh_button(self, obj):
        if obj.pk:
            return format_html(
                '<a class="default" href="{}" style="background: #417690; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px 0; font-size: 12px;" title="Fetch latest information from Wikidata API">🔄 Refresh from Wikidata</a>',
                reverse("admin:images_wikidataitem_refresh", args=[obj.pk]),
            )
        return '<span style="color: #999; font-style: italic;">Save item first</span>'

    refresh_button.short_description = "Actions"


class SubjectMappingInline(admin.TabularInline):
    """Inline editor for SubjectMapping relationships on Image admin"""

    model = SubjectMapping
    extra = 0
    fields = ("subject", "order")
    autocomplete_fields = ["subject"]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "description_truncated",
        "wikidata_item_link",
        "image_count",
        "created_at",
    )
    list_filter = ("created_at", "wikidata_item")
    search_fields = (
        "title",
        "description",
        "wikidata_item__wikidata_id",
        "wikidata_item__title",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ["wikidata_item"]

    fieldsets = (
        (
            "Subject Information",
            {"fields": ("title", "description")},
        ),
        (
            "Wikidata Link",
            {
                "fields": ("wikidata_item",),
                "description": "Optional link to Wikidata item for additional metadata",
            },
        ),
        (
            "System Information",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def description_truncated(self, obj):
        if obj.description:
            return (
                obj.description[:100] + "..."
                if len(obj.description) > 100
                else obj.description
            )
        return ""

    description_truncated.short_description = "Description"

    def wikidata_item_link(self, obj):
        if obj.wikidata_item:
            return format_html(
                '<a href="{}" target="_blank">{}</a>',
                obj.wikidata_item.wikidata_url,
                obj.wikidata_item.wikidata_id,
            )
        return "None"

    wikidata_item_link.short_description = "Wikidata"

    def image_count(self, obj):
        return obj.image_mappings.count()

    image_count.short_description = "Images"


@admin.register(SubjectMapping)
class SubjectMappingAdmin(admin.ModelAdmin):
    list_display = (
        "image_link",
        "subject_title",
        "subject_wikidata",
        "order",
        "created_at",
    )
    list_filter = ("created_at", "subject__wikidata_item")
    search_fields = (
        "image__title",
        "subject__title",
        "subject__description",
        "subject__wikidata_item__wikidata_id",
    )
    readonly_fields = ("created_at",)
    autocomplete_fields = ["image", "subject"]

    def image_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            obj.image.get_absolute_url(),
            obj.image.title if obj.image.title else f"Image {obj.image.id}",
        )

    image_link.short_description = "Image"

    def subject_title(self, obj):
        return obj.subject.title

    subject_title.short_description = "Subject"

    def subject_wikidata(self, obj):
        if obj.subject.wikidata_item:
            return format_html(
                '<a href="{}" target="_blank">{}</a>',
                obj.subject.wikidata_item.wikidata_url,
                obj.subject.wikidata_item.wikidata_id,
            )
        return "None"

    subject_wikidata.short_description = "Wikidata"


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """Admin configuration for SiteSettings singleton model"""

    def has_add_permission(self, request):
        # Prevent adding multiple instances
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of the settings instance
        return False

    fieldsets = (
        (
            "Homepage Content",
            {
                "fields": ("site_title", "site_subtitle"),
                "description": "Text displayed on the homepage",
            },
        ),
        (
            "Footer",
            {
                "fields": ("footer_content",),
                "description": "HTML content displayed in the site footer",
            },
        ),
    )


# Update the existing ImageAdmin to include subject inline
# Find the existing ImageAdmin and add the subject inline
class ImageAdminUpdated(ImageAdmin):
    inlines = [SubjectMappingInline]


# Unregister the existing ImageAdmin and register the updated one
admin.site.unregister(Image)
admin.site.register(Image, ImageAdminUpdated)


# Custom admin site configuration
admin.site.site_header = "Image Georeferencing Admin"
admin.site.site_title = "Georef Admin"
admin.site.index_title = "Georeferencing Administration"
