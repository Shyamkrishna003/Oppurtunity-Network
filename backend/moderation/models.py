from uuid import UUID

from django.conf import settings
from django.db import models

from common.models import TimestampedModel, UUIDModel


class TargetType(models.TextChoices):
    USER = "USER", "Person"
    ORGANIZATION = "ORGANIZATION", "Organization"
    COMMUNITY = "COMMUNITY", "Community"
    OPPORTUNITY = "OPPORTUNITY", "Opportunity"


class ReportCategory(models.TextChoices):
    SPAM = "SPAM", "Spam"
    SCAM = "SCAM", "Scam or fraud"
    HARASSMENT = "HARASSMENT", "Harassment or hate"
    INAPPROPRIATE = "INAPPROPRIATE", "Inappropriate content"
    MISLEADING = "MISLEADING", "False or misleading"
    OTHER = "OTHER", "Something else"


class ReportStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    ACTION_TAKEN = "ACTION_TAKEN", "Action taken"
    DISMISSED = "DISMISSED", "Dismissed"


class ActionType(models.TextChoices):
    # Opportunities.
    HIDE = "HIDE", "Hidden"
    REMOVE = "REMOVE", "Removed"
    RESTORE = "RESTORE", "Restored"
    # People.
    WARN = "WARN", "Warned"
    RESTRICT_POSTING = "RESTRICT_POSTING", "Restricted from posting"
    UNRESTRICT_POSTING = "UNRESTRICT_POSTING", "Posting restriction lifted"
    # People, organizations and communities.
    SUSPEND = "SUSPEND", "Suspended"
    UNSUSPEND = "UNSUSPEND", "Suspension lifted"
    # Organizations.
    VERIFY = "VERIFY", "Verified"
    UNVERIFY = "UNVERIFY", "Verification withdrawn"


# One column per kind of target, so each is a real foreign key.
_TARGET_FIELDS = {
    TargetType.USER: "target_user",
    TargetType.ORGANIZATION: "target_organization",
    TargetType.COMMUNITY: "target_community",
    TargetType.OPPORTUNITY: "target_opportunity",
}


def _exactly_the_named_target() -> models.Q:
    """``target_type`` names one of the target columns; that one is set and the rest empty."""
    condition = models.Q()
    for target_type, field in _TARGET_FIELDS.items():
        this = models.Q(target_type=target_type, **{f"{field}__isnull": False})
        for other in _TARGET_FIELDS.values():
            if other != field:
                this &= models.Q(**{f"{other}__isnull": True})
        condition |= this
    return condition


class _Targeted(models.Model):
    """Something that is about exactly one person, organization, community or opportunity."""

    target_type = models.CharField(max_length=12, choices=TargetType.choices)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    target_organization = models.ForeignKey(
        "organizations.Organization",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    target_community = models.ForeignKey(
        "communities.Community", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    target_opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True

    @property
    def target(self) -> models.Model:
        target: models.Model = getattr(self, _TARGET_FIELDS[TargetType(self.target_type)])
        return target

    @property
    def target_id(self) -> UUID:
        target_id: UUID = getattr(self, f"{_TARGET_FIELDS[TargetType(self.target_type)]}_id")
        return target_id


def target_field(target_type: str) -> str:
    return _TARGET_FIELDS[TargetType(target_type)]


class Report(_Targeted, TimestampedModel):
    """Someone telling the moderators that something breaks the rules.

    ``status`` only moves through ``policies.REPORT``. Who reported is never shown to the
    person or the owners of what was reported.
    """

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports_made"
    )
    category = models.CharField(max_length=14, choices=ReportCategory.choices)
    description = models.TextField(max_length=2000, blank=True)
    status = models.CharField(
        max_length=12, choices=ReportStatus.choices, default=ReportStatus.OPEN
    )
    # Whose moderators decide it: this community's, or (when empty) the platform's. Only a
    # report about an opportunity the community shows can be the community's.
    scope_community = models.ForeignKey(
        "communities.Community",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reports",
    )
    # The moderator who took it on.
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    # For the other moderators. Never shown to the reporter or the reported.
    resolution_note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=_exactly_the_named_target(), name="moderation_report_one_target"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ReportStatus.values),
                name="moderation_report_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(category__in=ReportCategory.values),
                name="moderation_report_category_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(scope_community__isnull=True)
                | models.Q(target_type=TargetType.OPPORTUNITY),
                name="moderation_report_community_scope_opportunity",
            ),
            # A person has at most one report in progress about the same thing.
            *(
                models.UniqueConstraint(
                    fields=["reporter", field],
                    condition=models.Q(status__in=[ReportStatus.OPEN, ReportStatus.UNDER_REVIEW]),
                    name=f"moderation_report_open_once_{target_type.lower()}",
                )
                for target_type, field in _TARGET_FIELDS.items()
            ),
        ]
        indexes = [
            # The queue: one status, oldest first.
            models.Index(fields=["status", "created_at"], name="moderation_report_queue"),
            models.Index(
                fields=["scope_community", "status", "created_at"],
                name="moderation_report_community",
            ),
            models.Index(fields=["reporter", "-created_at"], name="moderation_report_mine"),
            models.Index(fields=["target_opportunity", "status"], name="moderation_report_opp"),
        ]

    def __str__(self) -> str:
        return f"{self.category} report on {self.target_type} {self.target_id} ({self.status})"


class ModerationAction(_Targeted, UUIDModel):
    """Something a moderator did to a person, organization, community or opportunity.

    Append-only: undoing an action is another action (RESTORE), never an edit or a delete.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="moderation_actions"
    )
    action_type = models.CharField(max_length=20, choices=ActionType.choices)
    # The report that led to it, when one did.
    report = models.ForeignKey(
        Report, null=True, blank=True, on_delete=models.SET_NULL, related_name="actions"
    )
    reason = models.CharField(max_length=500)
    # For a suspension or a posting restriction: when it lapses. None means until lifted.
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=_exactly_the_named_target(), name="moderation_action_one_target"
            ),
            models.CheckConstraint(
                condition=models.Q(action_type__in=ActionType.values),
                name="moderation_action_type_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="moderation_action_needs_reason"
            ),
        ]
        indexes = [
            models.Index(
                fields=["target_opportunity", "-created_at"], name="moderation_action_opp"
            ),
            models.Index(fields=["actor", "-created_at"], name="moderation_action_actor"),
        ]

    def __str__(self) -> str:
        return f"{self.action_type} on {self.target_type} {self.target_id}"
