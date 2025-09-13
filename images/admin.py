from django.contrib import admin
from django.urls import path, reverse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.utils.html import format_html
import json
from .models import (
    Source,
    Collection,
    Image,
    Georeference,
    GeoreferenceValidation,
    ImageSkip,
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
    list_display = ("name", "source", "public", "url", "created_at", "image_count", "label_collection_button")
    list_filter = ("public", "source", "created_at")
    search_fields = ("name", "description", "source__name")
    readonly_fields = ("created_at", "updated_at")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:collection_id>/label/',
                self.admin_site.admin_view(self.label_collection),
                name='images_collection_label',
            ),
            path(
                '<int:collection_id>/label/update/',
                self.admin_site.admin_view(self.update_image_label),
                name='images_collection_update_label',
            ),
        ]
        return custom_urls + urls

    def image_count(self, obj):
        return obj.images.count()
    image_count.short_description = "Images"

    def label_collection_button(self, obj):
        url = reverse('admin:images_collection_label', args=[obj.pk])
        return format_html('<a class="button" href="{}">Label Collection</a>', url)
    label_collection_button.short_description = "Actions"

    def label_collection(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        images = collection.images.all().order_by('id')

        # Serialize image data for JavaScript
        image_data = []
        for image in images:
            image_data.append({
                'id': image.id,
                'title': image.title,
                'permalink': image.permalink,
                'description': image.description,
                'date_display': image.date_display,
                'difficulty': image.difficulty,
                'will_not_georef': image.will_not_georef,
                'absolute_url': image.get_absolute_url(),
            })

        context = {
            'collection': collection,
            'images': images,
            'image_data_json': json.dumps(image_data),
            'title': f'Label Collection: {collection.name}',
        }

        return render(request, 'admin/images/collection_label.html', context)

    def update_image_label(self, request, collection_id):
        if request.method != 'POST':
            return JsonResponse({'error': 'POST required'}, status=400)

        image_id = request.POST.get('image_id')
        difficulty = request.POST.get('difficulty')
        will_not_georef = request.POST.get('will_not_georef') == 'true'

        try:
            image = get_object_or_404(Image, id=image_id, collection_id=collection_id)

            if difficulty and difficulty != 'none':
                image.difficulty = difficulty
            elif difficulty == 'none':
                image.difficulty = None

            image.will_not_georef = will_not_georef
            image.save(update_fields=['difficulty', 'will_not_georef'])

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = (
        "title_or_id",
        "collection",
        "date_display",
        "difficulty",
        "will_not_georef",
        "skip_count",
        "georeference_status",
    )
    list_filter = ("difficulty", "will_not_georef", "collection__source")
    search_fields = ("title", "description", "collection__name")
    readonly_fields = ("created_at", "updated_at", "skip_count")
    fieldsets = (
        (
            "Basic Information",
            {"fields": ("collection", "title", "permalink", "description", "ref")},
        ),
        (
            "Date Information",
            {
                "fields": ("original_date", "edtf_date"),
                "description": "Leave fields blank if date information is not available",
            },
        ),
        ("Georeferencing", {"fields": ("difficulty", "will_not_georef")}),
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
        "latitude",
        "longitude",
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
    fieldsets = (
        ("Image Information", {"fields": ("image",)}),
        ("Coordinates", {"fields": ("latitude", "longitude", "direction")}),
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


# Custom admin site configuration
admin.site.site_header = "Image Georeferencing Admin"
admin.site.site_title = "Georef Admin"
admin.site.index_title = "Georeferencing Administration"
