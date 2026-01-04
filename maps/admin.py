from django.contrib import admin

from .models import LayerCollection, MapLayer


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
            {"fields": ("name", "slug", "collection", "order", "description")},
        ),
        ("Map Data", {"fields": ("type", "url", "attribution")}),
        ("Links", {"fields": ("source_link", "oim_link")}),
        (
            "System Information",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
