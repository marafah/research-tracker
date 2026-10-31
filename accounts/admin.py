from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "full_name", "affiliation", "is_external", "is_staff", "is_active")
    list_filter = ("is_external", "is_staff", "is_active")
    search_fields = ("email", "full_name", "full_name_ar", "affiliation", "orcid")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "full_name_ar", "title", "affiliation", "department",
                                "country", "orcid", "scholar_url", "phone", "is_external")}),
        ("Preferences", {"fields": ("preferred_language", "email_reminders", "weekly_digest")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
