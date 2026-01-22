from django.contrib import admin

from .models import (
    GeoreferenceGroup,
    GeoreferenceGroupMember,
    SitewideMilestone,
    UserMilestone,
)


class GeoreferenceGroupMemberInline(admin.TabularInline):
    model = GeoreferenceGroupMember
    extra = 0
    readonly_fields = ("georeference", "aerial_georeference", "added_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(GeoreferenceGroup)
class GeoreferenceGroupAdmin(admin.ModelAdmin):
    list_display = ("user", "count", "started_at", "ended_at")
    list_filter = ("started_at", "ended_at")
    search_fields = ("user__username", "user__first_name")
    readonly_fields = ("user", "started_at", "ended_at", "count")
    ordering = ("-ended_at",)
    inlines = [GeoreferenceGroupMemberInline]

    def has_add_permission(self, request):
        return False


@admin.register(GeoreferenceGroupMember)
class GeoreferenceGroupMemberAdmin(admin.ModelAdmin):
    list_display = ("group", "georeference", "aerial_georeference", "added_at")
    list_filter = ("added_at",)
    readonly_fields = ("group", "georeference", "aerial_georeference", "added_at")
    ordering = ("-added_at",)

    def has_add_permission(self, request):
        return False


@admin.register(UserMilestone)
class UserMilestoneAdmin(admin.ModelAdmin):
    list_display = ("user", "count", "reached_at")
    list_filter = ("count", "reached_at")
    search_fields = ("user__username", "user__first_name")
    readonly_fields = ("user", "count", "reached_at")
    ordering = ("-reached_at",)

    def has_add_permission(self, request):
        return False


@admin.register(SitewideMilestone)
class SitewideMilestoneAdmin(admin.ModelAdmin):
    list_display = ("count", "reached_at")
    list_filter = ("count", "reached_at")
    readonly_fields = ("count", "reached_at")
    ordering = ("-reached_at",)

    def has_add_permission(self, request):
        return False
