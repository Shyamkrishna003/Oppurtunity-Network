from django.contrib import admin

from organizations.models import Organization, OrganizationInvitation, OrganizationMember


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "slug", "verification_status", "status", "created_at")
    list_filter = ("verification_status", "status")
    search_fields = ("name", "slug")
    readonly_fields = ("slug", "created_at", "updated_at")


@admin.register(OrganizationMember)
class OrganizationMemberAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("organization", "user", "role", "status", "joined_at")
    list_filter = ("role", "status")
    search_fields = ("organization__name", "user__email")
    raw_id_fields = ("organization", "user")


@admin.register(OrganizationInvitation)
class OrganizationInvitationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("organization", "email", "role", "status", "expires_at")
    list_filter = ("status", "role")
    search_fields = ("organization__name", "email")
    raw_id_fields = ("organization", "invited_by")
    exclude = ("token_hash",)
