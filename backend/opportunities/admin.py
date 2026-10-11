from django.contrib import admin

from jobs.models import JobDetail
from opportunities.models import Opportunity, OpportunityCommunity


class JobDetailInline(admin.StackedInline):  # type: ignore[type-arg]
    model = JobDetail
    can_delete = False


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("title", "type", "status", "moderation_status", "organization", "deadline")
    list_filter = ("type", "status", "moderation_status", "visibility")
    search_fields = ("title", "organization__name")
    raw_id_fields = ("creator", "organization")
    # The lifecycle is changed through the application, where it is checked and audited.
    readonly_fields = ("type", "status", "published_at", "closed_at", "close_reason", "skills_text")
    inlines = (JobDetailInline,)


@admin.register(OpportunityCommunity)
class OpportunityCommunityAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("opportunity", "community", "status", "is_featured", "created_at")
    list_filter = ("status", "is_featured")
    raw_id_fields = ("opportunity", "community", "submitted_by", "reviewed_by")
