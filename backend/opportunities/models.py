from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models.functions import Upper

from common.choices import WorkMode
from common.models import TimestampedModel, UUIDModel


class OpportunityType(models.TextChoices):
    JOB = "JOB", "Job"
    EVENT = "EVENT", "Event"


class OpportunityStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    CLOSED = "CLOSED", "Closed"
    EXPIRED = "EXPIRED", "Expired"
    ARCHIVED = "ARCHIVED", "Archived"


class OpportunityVisibility(models.TextChoices):
    PUBLIC = "PUBLIC", "Everyone"
    COMMUNITY = "COMMUNITY", "Members of the communities it is shared with"
    ORGANIZATION = "ORGANIZATION", "Members of the organization"


class ModerationStatus(models.TextChoices):
    VISIBLE = "VISIBLE", "Visible"
    HIDDEN = "HIDDEN", "Hidden"
    REMOVED = "REMOVED", "Removed"


class CloseReason(models.TextChoices):
    FILLED = "FILLED", "Filled"
    CANCELLED = "CANCELLED", "Cancelled"
    OTHER = "OTHER", "Other"


class DistributionStatus(models.TextChoices):
    PENDING = "PENDING", "Waiting for review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    REMOVED = "REMOVED", "Removed"


# Once published, an opportunity always has a publication date.
_LIVE_OR_PAST = (
    OpportunityStatus.PUBLISHED,
    OpportunityStatus.CLOSED,
    OpportunityStatus.EXPIRED,
    OpportunityStatus.ARCHIVED,
)


class Opportunity(TimestampedModel):
    """What every opportunity has in common, whatever its type.

    Type-specific fields live in a one-to-one detail table (``jobs.JobDetail`` and so on)
    whose primary key is this row's ID, so the feed, search, visibility and distribution only
    ever query this narrow table. ``type`` never changes after creation.

    The owner is the organization when one is set, otherwise the creator. ``status`` is the
    publication lifecycle; ``moderation_status`` is separate, so hiding an opportunity does
    not disturb where it is in that lifecycle.
    """

    type = models.CharField(max_length=8, choices=OpportunityType.choices)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="opportunities_created"
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="opportunities",
    )
    title = models.CharField(max_length=160)
    description = models.TextField(max_length=10000, blank=True)
    status = models.CharField(
        max_length=10, choices=OpportunityStatus.choices, default=OpportunityStatus.DRAFT
    )
    visibility = models.CharField(
        max_length=12, choices=OpportunityVisibility.choices, default=OpportunityVisibility.PUBLIC
    )
    moderation_status = models.CharField(
        max_length=8, choices=ModerationStatus.choices, default=ModerationStatus.VISIBLE
    )
    # Blank while drafting; required to publish.
    work_mode = models.CharField(max_length=8, choices=WorkMode.choices, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    region = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    deadline = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=10, choices=CloseReason.choices, blank=True)
    skills = models.ManyToManyField(
        "taxonomy.Skill", through="OpportunitySkill", related_name="opportunities"
    )
    # Search columns, maintained by the service whenever the text they are built from changes
    # (a generated column cannot reach the skill and organization names).
    skills_text = models.TextField(blank=True)
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        verbose_name_plural = "opportunities"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(type__in=OpportunityType.values),
                name="opportunities_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=OpportunityStatus.values),
                name="opportunities_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(visibility__in=OpportunityVisibility.values),
                name="opportunities_visibility_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(moderation_status__in=ModerationStatus.values),
                name="opportunities_moderation_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(work_mode__in=["", *WorkMode.values]),
                name="opportunities_work_mode_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(close_reason__in=["", *CloseReason.values]),
                name="opportunities_close_reason_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(country_code=Upper("country_code")),
                name="opportunities_country_uppercase",
            ),
            models.CheckConstraint(
                condition=models.Q(status=OpportunityStatus.DRAFT, published_at__isnull=True)
                | models.Q(status__in=_LIVE_OR_PAST, published_at__isnull=False),
                name="opportunities_published_at_matches_status",
            ),
            models.CheckConstraint(
                condition=~models.Q(visibility=OpportunityVisibility.ORGANIZATION)
                | models.Q(organization__isnull=False),
                name="opportunities_org_visibility_needs_org",
            ),
        ]
        indexes = [
            # The feed: newest published, visible opportunities first.
            models.Index(
                fields=["-published_at", "-id"],
                condition=models.Q(
                    status=OpportunityStatus.PUBLISHED, moderation_status=ModerationStatus.VISIBLE
                ),
                name="opportunities_feed",
            ),
            models.Index(fields=["type", "status", "deadline"], name="opportunities_type_status"),
            models.Index(fields=["organization", "status"], name="opportunities_organization"),
            models.Index(fields=["creator", "status"], name="opportunities_creator"),
            # The expiry sweep: published opportunities whose deadline has passed.
            models.Index(
                fields=["deadline"],
                condition=models.Q(status=OpportunityStatus.PUBLISHED),
                name="opportunities_expiry",
            ),
            models.Index(fields=["country_code", "city"], name="opportunities_location"),
            GinIndex(fields=["search_vector"], name="opportunities_search"),
            GinIndex(fields=["title"], opclasses=["gin_trgm_ops"], name="opportunities_title_trgm"),
        ]

    def __str__(self) -> str:
        return self.title


class OpportunitySkill(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="+")
    skill = models.ForeignKey("taxonomy.Skill", on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "skill"], name="opportunities_skill_unique"
            ),
        ]
        indexes = [
            # "Opportunities that need this skill": the filter and the relevance match.
            models.Index(fields=["skill", "opportunity"], name="opportunities_by_skill"),
        ]

    def __str__(self) -> str:
        return f"{self.opportunity_id} needs {self.skill_id}"


class OpportunityCommunity(TimestampedModel):
    """An opportunity shared with one community. The community owns the decision to show it,
    and each community decides independently."""

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="distributions"
    )
    community = models.ForeignKey(
        "communities.Community", on_delete=models.CASCADE, related_name="distributions"
    )
    status = models.CharField(max_length=8, choices=DistributionStatus.choices)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=300, blank=True)
    is_featured = models.BooleanField(default=False)
    featured_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "community"], name="opportunities_distribution_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=DistributionStatus.values),
                name="opportunities_distribution_status_valid",
            ),
            # Only something a community shows can be featured in it.
            models.CheckConstraint(
                condition=models.Q(is_featured=False)
                | models.Q(status=DistributionStatus.APPROVED),
                name="opportunities_featured_needs_approval",
            ),
        ]
        indexes = [
            models.Index(
                fields=["community", "status", "created_at"], name="opportunities_dist_queue"
            ),
            models.Index(
                fields=["community", "is_featured"],
                condition=models.Q(status=DistributionStatus.APPROVED),
                name="opportunities_dist_featured",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.opportunity_id} in {self.community_id} ({self.status})"


class SavedOpportunity(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_opportunities"
    )
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="saves")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "opportunity"], name="opportunities_save_unique"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="opportunities_saved_recent"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} saved {self.opportunity_id}"
