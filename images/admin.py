import json

from django import forms
from django.contrib import admin
from django.contrib.auth.models import User
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
    PreCollection,
    PreImage,
    SiteSettings,
    Source,
    SubjectMapping,
)


class UserDisplayNameChoiceField(forms.ModelChoiceField):
    """ModelChoiceField that displays user display names instead of usernames."""

    def label_from_instance(self, obj):
        return obj.get_display_name()


class GeoreferenceAdminForm(forms.ModelForm):
    georeferenced_by = UserDisplayNameChoiceField(
        queryset=User.objects.all().order_by("first_name", "username"),
        required=False,
    )

    class Meta:
        model = Georeference
        fields = "__all__"


class GeoreferenceValidationAdminForm(forms.ModelForm):
    validated_by = UserDisplayNameChoiceField(
        queryset=User.objects.all().order_by("first_name", "username"),
        required=False,
    )

    class Meta:
        model = GeoreferenceValidation
        fields = "__all__"


class ImageSkipAdminForm(forms.ModelForm):
    user = UserDisplayNameChoiceField(
        queryset=User.objects.all().order_by("first_name", "username"),
        required=False,
    )

    class Meta:
        model = ImageSkip
        fields = "__all__"


class UserDisplayNameFilter(admin.SimpleListFilter):
    """
    Custom filter that displays user display names instead of raw usernames.
    """

    title = "user"
    parameter_name = "user_id"

    def __init__(self, request, params, model, model_admin):
        self.field_name = getattr(self, "field_name", "georeferenced_by")
        super().__init__(request, params, model, model_admin)

    def lookups(self, request, model_admin):
        from django.contrib.auth.models import User

        field_name = self.field_name
        user_ids = (
            model_admin.get_queryset(request)
            .exclude(**{field_name: None})
            .values_list(field_name, flat=True)
            .distinct()
        )
        users = User.objects.filter(id__in=user_ids).order_by("first_name", "username")
        return [(user.id, user.get_display_name()) for user in users]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(**{self.field_name: self.value()})
        return queryset


class GeoreferencedByFilter(UserDisplayNameFilter):
    """Filter for the georeferenced_by field."""

    title = "georeferenced by"
    parameter_name = "georeferenced_by"
    field_name = "georeferenced_by"


class ValidatedByFilter(UserDisplayNameFilter):
    """Filter for the validated_by field."""

    title = "validated by"
    parameter_name = "validated_by"
    field_name = "validated_by"


class SkippedByFilter(UserDisplayNameFilter):
    """Filter for the user field on ImageSkip."""

    title = "user"
    parameter_name = "user"
    field_name = "user"


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
    form = GeoreferenceAdminForm
    list_display = (
        "image",
        "point",
        "direction",
        "georeferenced_by_display",
        "georeferenced_at",
        "validation_count",
    )
    list_filter = (GeoreferencedByFilter, "georeferenced_at")
    search_fields = (
        "image__title",
        "image__collection__name",
        "georeferenced_by__username",
        "georeferenced_by__first_name",
    )

    def georeferenced_by_display(self, obj):
        if obj.georeferenced_by:
            return obj.georeferenced_by.get_display_name()
        return None

    georeferenced_by_display.short_description = "Georeferenced By"
    georeferenced_by_display.admin_order_field = "georeferenced_by__first_name"
    readonly_fields = ("georeferenced_at", "updated_at", "validation_count")
    autocomplete_fields = ["image"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        # Remove add, change, delete buttons for image field
        if "image" in form.base_fields:
            form.base_fields["image"].widget.can_add_related = False
            form.base_fields["image"].widget.can_change_related = False
            form.base_fields["image"].widget.can_delete_related = False

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
    form = GeoreferenceValidationAdminForm
    list_display = (
        "georeference",
        "validation",
        "validated_by_display",
        "validated_at",
    )
    list_filter = ("validation", ValidatedByFilter, "validated_at")
    search_fields = (
        "georeference__image__title",
        "validated_by__username",
        "validated_by__first_name",
        "notes",
    )
    readonly_fields = ("validated_at",)

    def validated_by_display(self, obj):
        if obj.validated_by:
            return obj.validated_by.get_display_name()
        return None

    validated_by_display.short_description = "Validated By"
    validated_by_display.admin_order_field = "validated_by__first_name"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("georeference__image", "validated_by")
        )


@admin.register(ImageSkip)
class ImageSkipAdmin(admin.ModelAdmin):
    form = ImageSkipAdminForm
    list_display = ("image", "user_display", "reason", "skipped_at")
    list_filter = (SkippedByFilter, "skipped_at", "reason")
    search_fields = ("image__title", "user__username", "user__first_name", "reason")
    readonly_fields = ("skipped_at",)

    def user_display(self, obj):
        if obj.user:
            return obj.user.get_display_name()
        return None

    user_display.short_description = "User"
    user_display.admin_order_field = "user__first_name"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("image", "user")


class SubjectMappingInline(admin.TabularInline):
    """Inline editor for SubjectMapping relationships on Image admin"""

    model = SubjectMapping
    extra = 0
    fields = ("subject", "order")
    autocomplete_fields = ["subject"]


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
        (
            "Contact",
            {
                "fields": ("admin_email",),
                "description": "Admin contact email for external API requests",
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
admin.site.site_header = "Yesterdays Admin"
admin.site.site_title = "Yesterdays Admin"
admin.site.index_title = "Yesterdays Administration"
