from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from common.models import TimestampedModel


class CommunityRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    ADMIN = "ADMIN", "Admin"
    MODERATOR = "MODERATOR", "Moderator"
    MEMBER = "MEMBER", "Member"


class MemberStatus(models.TextChoices):
    PENDING = "PENDING", "Asked to join"
    INVITED = "INVITED", "Invited"
    ACTIVE = "ACTIVE", "Active"
    REJECTED = "REJECTED", "Rejected"
    LEFT = "LEFT", "Left"
    REMOVED = "REMOVED", "Removed"
    BANNED = "BANNED", "Banned"


class JoinPolicy(models.TextChoices):
    OPEN = "OPEN", "Anyone can join"
    APPROVAL = "APPROVAL", "Admins approve each request"
    INVITE_ONLY = "INVITE_ONLY", "By invitation only"


class PostingPolicy(models.TextChoices):
    ADMINS_ONLY = "ADMINS_ONLY", "Admins only"
    MEMBERS_WITH_APPROVAL = "MEMBERS_WITH_APPROVAL", "Members, after review"
    MEMBERS_AUTO = "MEMBERS_AUTO", "Members, without review"


class CommunityVisibility(models.TextChoices):
    PUBLIC = "PUBLIC", "Public"
    PRIVATE = "PRIVATE", "Private"


class CommunityStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"


class Community(TimestampedModel):
    """A tenant: a group that opportunities are distributed to. Owned by its OWNER members."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(max_length=4000, blank=True)
    category = models.CharField(max_length=60, blank=True)
    # Storage keys of re-encoded images; never client-supplied filenames.
    logo = models.CharField(max_length=255, blank=True)
    cover = models.CharField(max_length=255, blank=True)
    join_policy = models.CharField(
        max_length=12, choices=JoinPolicy.choices, default=JoinPolicy.OPEN
    )
    posting_policy = models.CharField(
        max_length=24, choices=PostingPolicy.choices, default=PostingPolicy.MEMBERS_WITH_APPROVAL
    )
    # A private community is invisible to everyone but its members and the people invited.
    visibility = models.CharField(
        max_length=8, choices=CommunityVisibility.choices, default=CommunityVisibility.PUBLIC
    )
    is_verified = models.BooleanField(default=False)
    status = models.CharField(
        max_length=10, choices=CommunityStatus.choices, default=CommunityStatus.ACTIVE
    )

    class Meta:
        verbose_name_plural = "communities"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(join_policy__in=JoinPolicy.values),
                name="communities_community_join_policy_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(posting_policy__in=PostingPolicy.values),
                name="communities_community_posting_policy_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(visibility__in=CommunityVisibility.values),
                name="communities_community_visibility_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=CommunityStatus.values),
                name="communities_community_status_valid",
            ),
        ]
        indexes = [
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="communities_name_trgm"),
            models.Index(fields=["category"], name="communities_category"),
        ]

    def __str__(self) -> str:
        return self.name


class CommunityMember(TimestampedModel):
    """A user's relationship with a community, in every state from request to ban.

    One row per pair, reused when someone leaves and returns, so a ban or the history of a
    membership cannot be escaped by rejoining.
    """

    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="community_memberships"
    )
    role = models.CharField(
        max_length=10, choices=CommunityRole.choices, default=CommunityRole.MEMBER
    )
    status = models.CharField(max_length=8, choices=MemberStatus.choices)
    notify_new_opportunities = models.BooleanField(default=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # When the current period of active membership began; null if never active.
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["community", "user"], name="communities_member_unique"),
            models.CheckConstraint(
                condition=models.Q(role__in=CommunityRole.values),
                name="communities_member_role_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=MemberStatus.values),
                name="communities_member_status_valid",
            ),
            # Elevated roles exist only on active memberships.
            models.CheckConstraint(
                condition=models.Q(status=MemberStatus.ACTIVE)
                | models.Q(role=CommunityRole.MEMBER),
                name="communities_member_role_requires_active",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="communities_member_user"),
            models.Index(fields=["community", "status", "role"], name="communities_member_status"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.community_id} ({self.role}, {self.status})"


class CommunityRule(models.Model):
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="rules")
    position = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=2000, blank=True)

    class Meta:
        ordering = ("position",)
        constraints = [
            models.UniqueConstraint(
                fields=["community", "position"], name="communities_rule_position_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.title
