from django.contrib import admin

from communities.models import Community, CommunityMember, CommunityRule


class RuleInline(admin.TabularInline):  # type: ignore[type-arg]
    model = CommunityRule
    extra = 0


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "slug", "visibility", "join_policy", "is_verified", "status")
    list_filter = ("visibility", "join_policy", "is_verified", "status")
    search_fields = ("name", "slug")
    readonly_fields = ("slug", "created_at", "updated_at")
    inlines = (RuleInline,)


@admin.register(CommunityMember)
class CommunityMemberAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("community", "user", "role", "status", "joined_at")
    list_filter = ("role", "status")
    search_fields = ("community__name", "user__email")
    raw_id_fields = ("community", "user", "invited_by")
