from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    Address,
    Business,
    Occupation,
    OsmElement,
    Person,
    Subject,
    WikidataItem,
)


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
                name="subjects_wikidataitem_refresh",
            ),
        ]
        return custom_urls + urls

    def refresh_individual_item(self, request, object_id):
        """Refresh Wikidata information for a single item"""
        wikidata_item = get_object_or_404(WikidataItem, pk=object_id)

        messages.info(
            request,
            f"Refreshing Wikidata information for {wikidata_item.wikidata_id}... This may take a moment.",
        )

        try:
            if wikidata_item.populate_from_wikidata():
                wikidata_item.save()
                messages.success(
                    request,
                    f"Successfully refreshed Wikidata information for {wikidata_item.wikidata_id}. "
                    f"Title: {wikidata_item.title}",
                )
            else:
                messages.warning(
                    request,
                    f"No data found for {wikidata_item.wikidata_id}. "
                    f"The item may not exist or may not have English labels.",
                )
        except ValidationError as e:
            error_msg = str(e)
            if "Network error" in error_msg:
                messages.error(
                    request,
                    f"Network error refreshing {wikidata_item.wikidata_id}. "
                    f"The system automatically retried the request. Please try again if this persists.",
                )
            else:
                messages.error(
                    request, f"Error refreshing Wikidata information: {error_msg}"
                )
        except Exception as e:
            messages.error(
                request, f"Unexpected error refreshing Wikidata information: {e}"
            )

        return HttpResponseRedirect(
            reverse("admin:subjects_wikidataitem_change", args=[object_id])
        )

    def refresh_selected_wikidata_items(self, request, queryset):
        """Refresh Wikidata information for selected items"""
        total_count = queryset.count()
        updated_count = 0
        failed_count = 0
        network_errors = 0
        error_messages = []

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

        if updated_count > 0:
            self.message_user(
                request, f"Successfully updated {updated_count} Wikidata item(s)."
            )

        if failed_count > 0:
            error_msg = (
                f"Failed to update {failed_count} of {total_count} Wikidata item(s)."
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
                '<a class="default" href="{}" style="background: #417690; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px 0; font-size: 12px;" title="Fetch latest information from Wikidata API">Refresh from Wikidata</a>',
                reverse("admin:subjects_wikidataitem_refresh", args=[obj.pk]),
            )
        return '<span style="color: #999; font-style: italic;">Save item first</span>'

    refresh_button.short_description = "Actions"


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ["housenumber", "street", "city", "state", "postcode"]
    search_fields = ["housenumber", "street", "city", "state", "postcode"]


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ["last_name", "first_name", "middle_name", "birth_date"]
    search_fields = ["first_name", "middle_name", "last_name"]


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Occupation)
class OccupationAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


class OsmElementInline(admin.TabularInline):
    model = OsmElement
    extra = 0
    fields = ("osm_id", "geometry_area", "updated_at")
    readonly_fields = ("osm_id", "geometry_area", "updated_at")
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OsmElement)
class OsmElementAdmin(admin.ModelAdmin):
    list_display = ("osm_id", "subject", "geometry_area", "updated_at", "created_at")
    list_filter = ("updated_at", "created_at")
    search_fields = ("osm_id", "subject__title")
    readonly_fields = ("created_at", "updated_at", "geometry_area")
    autocomplete_fields = ["subject"]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "description_truncated",
        "wikidata_item_link",
        "osm_element_count",
        "image_count",
        "ancestor_count",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = (
        "title",
        "description",
        "wikidata_item__wikidata_id",
        "wikidata_item__title",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ["wikidata_item"]
    inlines = [OsmElementInline]

    fieldsets = (
        (
            "Subject Information",
            {"fields": ("title", "slug", "description")},
        ),
        (
            "Linked Data",
            {
                "fields": ("wikidata_item",),
                "description": "Optional link to Wikidata. OSM elements are shown below.",
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

    def osm_element_count(self, obj):
        return obj.osm_elements.count()

    osm_element_count.short_description = "OSM Elements"

    def image_count(self, obj):
        return obj.image_mappings.count()

    image_count.short_description = "Images"

    def ancestor_count(self, obj):
        return obj.ancestors.count()

    ancestor_count.short_description = "Ancestors"
