from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    Address,
    Directory,
    Entry,
    EntryBusinessLink,
    EntryOccupationLink,
    EntryPersonLink,
    OCRModel,
    Page,
)


class PageInline(admin.TabularInline):
    model = Page
    extra = 0
    readonly_fields = ["uuid", "image_url", "created_at"]
    fields = ["uuid", "order", "original_filename", "image_url", "created_at"]


@admin.register(Directory)
class DirectoryAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "created_at"]
    prepopulated_fields = {"slug": ("title",)}
    inlines = [PageInline]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "ocr_prompt":
            kwargs["widget"] = forms.Textarea(attrs={"rows": 20, "cols": 120})
        return super().formfield_for_dbfield(db_field, request, **kwargs)


@admin.register(OCRModel)
class OCRModelAdmin(admin.ModelAdmin):
    list_display = ["name", "identifier", "order"]
    list_editable = ["order"]
    search_fields = ["name", "identifier"]
    ordering = ["order", "name"]


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ["directory", "order", "uuid", "tile_status", "created_at"]
    list_filter = ["directory", "tile_status"]
    search_fields = ["directory__title", "original_filename"]
    readonly_fields = ["uuid", "regenerate_tiles_button"]

    @admin.display(description="Actions")
    def regenerate_tiles_button(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("admin:directories_page_regenerate_tiles", args=[obj.pk])
        return format_html('<a class="button" href="{}">Regenerate Tiles</a>', url)

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/regenerate-tiles/",
                self.admin_site.admin_view(self.regenerate_tiles_view),
                name="directories_page_regenerate_tiles",
            ),
        ]
        return custom_urls + super().get_urls()

    def regenerate_tiles_view(self, request, object_id):
        from .tasks import generate_iiif_tiles

        page = self.get_object(request, object_id)
        page.tile_status = "pending"
        page.tile_error = ""
        page.save(update_fields=["tile_status", "tile_error"])
        generate_iiif_tiles.apply_async(args=[page.id])
        self.message_user(request, f"Tile generation queued for page {page.uuid}.")
        return redirect(reverse("admin:directories_page_change", args=[page.pk]))


class EntryPersonLinkInline(admin.TabularInline):
    model = EntryPersonLink
    extra = 0
    autocomplete_fields = ["person"]


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0
    fields = ("type", "housenumber", "street", "city", "state", "postcode")


class EntryBusinessLinkInline(admin.TabularInline):
    model = EntryBusinessLink
    extra = 0
    autocomplete_fields = ["business"]


class EntryOccupationLinkInline(admin.TabularInline):
    model = EntryOccupationLink
    extra = 0
    autocomplete_fields = ["occupation"]


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ["id", "page", "original_text"]
    list_filter = ["page__directory"]
    autocomplete_fields = ["page"]
    inlines = [
        EntryPersonLinkInline,
        AddressInline,
        EntryBusinessLinkInline,
        EntryOccupationLinkInline,
    ]
