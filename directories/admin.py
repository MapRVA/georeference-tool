from django import forms
from django.contrib import admin

from .models import (
    Directory,
    Entry,
    EntryAddressLink,
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
    list_display = ["directory", "order", "uuid", "created_at"]
    list_filter = ["directory"]
    search_fields = ["directory__title", "original_filename"]
    readonly_fields = ["uuid"]


class EntryPersonLinkInline(admin.TabularInline):
    model = EntryPersonLink
    extra = 0
    autocomplete_fields = ["person"]


class EntryAddressLinkInline(admin.TabularInline):
    model = EntryAddressLink
    extra = 0
    autocomplete_fields = ["address"]


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
        EntryAddressLinkInline,
        EntryBusinessLinkInline,
        EntryOccupationLinkInline,
    ]
