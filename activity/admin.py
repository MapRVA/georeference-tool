from django.contrib import admin

from .models import (
    GeoreferenceGroup,
    GeoreferenceGroupMember,
    SitewideMilestone,
    SubjectIntroduction,
    SubjectMappingActivityGroup,
    UserMilestone,
)


class UserDisplayNameFilter(admin.SimpleListFilter):
    """
    Custom filter that displays user display names instead of raw usernames.
    """

    title = "user"
    parameter_name = "user"
    field_name = "user"

    def lookups(self, request, model_admin):
        from django.contrib.auth.models import User

        user_ids = (
            model_admin.get_queryset(request)
            .exclude(user=None)
            .values_list("user", flat=True)
            .distinct()
        )
        users = User.objects.filter(id__in=user_ids).order_by("first_name", "username")
        return [(user.id, user.get_display_name()) for user in users]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(user=self.value())
        return queryset


class GeoreferenceGroupMemberInline(admin.TabularInline):
    model = GeoreferenceGroupMember
    extra = 0
    readonly_fields = ("georeference", "aerial_georeference", "added_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(GeoreferenceGroup)
class GeoreferenceGroupAdmin(admin.ModelAdmin):
    list_display = ("user_display", "count", "started_at", "ended_at")
    list_filter = (UserDisplayNameFilter, "started_at", "ended_at")
    search_fields = ("user__username", "user__first_name")
    readonly_fields = ("user_display", "started_at", "ended_at", "count")
    ordering = ("-ended_at",)
    inlines = [GeoreferenceGroupMemberInline]
    fields = ("user_display", "count", "started_at", "ended_at")

    def user_display(self, obj):
        if obj.user:
            return obj.user.get_display_name()
        return None

    user_display.short_description = "User"
    user_display.admin_order_field = "user__first_name"

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
    list_display = ("user_display", "count", "reached_at")
    list_filter = (UserDisplayNameFilter, "count", "reached_at")
    search_fields = ("user__username", "user__first_name")
    readonly_fields = ("user_display", "count", "reached_at")
    ordering = ("-reached_at",)
    fields = ("user_display", "count", "reached_at")

    def user_display(self, obj):
        if obj.user:
            return obj.user.get_display_name()
        return None

    user_display.short_description = "User"
    user_display.admin_order_field = "user__first_name"

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


@admin.register(SubjectIntroduction)
class SubjectIntroductionAdmin(admin.ModelAdmin):
    list_display = ("subject", "user_display", "image", "created_at")
    list_filter = ("created_at",)
    search_fields = (
        "subject__title",
        "user__username",
        "user__first_name",
        "image__title",
    )
    readonly_fields = ("subject", "user", "image", "created_at")
    ordering = ("-created_at",)

    def user_display(self, obj):
        return obj.user.get_display_name() if obj.user else None

    user_display.short_description = "User"
    user_display.admin_order_field = "user__first_name"

    def has_add_permission(self, request):
        return False


@admin.register(SubjectMappingActivityGroup)
class SubjectMappingActivityGroupAdmin(admin.ModelAdmin):
    list_display = ("user_display", "action", "subject", "count", "started_at", "ended_at")
    list_filter = (UserDisplayNameFilter, "action", "started_at", "ended_at")
    search_fields = (
        "user__username",
        "user__first_name",
        "subject__title",
    )
    readonly_fields = (
        "user",
        "subject",
        "action",
        "started_at",
        "ended_at",
        "count",
    )
    ordering = ("-ended_at",)

    def user_display(self, obj):
        return obj.user.get_display_name() if obj.user else None

    user_display.short_description = "User"
    user_display.admin_order_field = "user__first_name"

    def has_add_permission(self, request):
        return False
