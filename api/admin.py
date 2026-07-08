from django.contrib import admin

from .models import ApplicationConsent


class ApplicationConsentAdmin(admin.ModelAdmin):
    list_display = ("user", "application", "scope", "created_at", "updated_at")
    list_filter = ("application",)
    search_fields = ("user__username", "application__name")
    raw_id_fields = ("user", "application")


admin.site.register(ApplicationConsent, ApplicationConsentAdmin)
