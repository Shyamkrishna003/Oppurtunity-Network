from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Lower, Upper

from common.models import TimestampedModel


class OrganizationRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    ADMIN = "ADMIN", "Admin"
    RECRUITER = "RECRUITER", "Recruiter"
    MEMBER = "MEMBER", "Member"


class MembershipStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    LEFT = "LEFT", "Left"
    REMOVED = "REMOVED", "Removed"


class VerificationStatus(models.TextChoices):
    UNVERIFIED = "UNVERIFIED", "Unverified"
    PENDING = "PENDING", "Pending"
    VERIFIED = "VERIFIED", "Verified"
    REJECTED = "REJECTED", "Rejected"


class OrganizationStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"


class InvitationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    DECLINED = "DECLINED", "Declined"
    REVOKED = "REVOKED", "Revoked"
    EXPIRED = "EXPIRED", "Expired"


class Organization(TimestampedModel):
    """A tenant. It is owned by its members with the OWNER role, not by a single user."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(max_length=4000, blank=True)
    website = models.URLField(blank=True)
    industry = models.CharField(max_length=80, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    region = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    # Storage key of the re-encoded image; never a client-supplied filename.
    logo = models.CharField(max_length=255, blank=True)
    verification_status = models.CharField(
        max_length=12, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    status = models.CharField(
        max_length=10, choices=OrganizationStatus.choices, default=OrganizationStatus.ACTIVE
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(verification_status__in=VerificationStatus.values),
                name="organizations_organization_verification_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=OrganizationStatus.values),
                name="organizations_organization_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(country_code=Upper("country_code")),
                name="organizations_organization_country_uppercase",
            ),
        ]
        indexes = [
            GinIndex(
                fields=["name"], opclasses=["gin_trgm_ops"], name="organizations_org_name_trgm"
            ),
            models.Index(fields=["verification_status"], name="organizations_org_verif"),
        ]

    def __str__(self) -> str:
        return self.name


class OrganizationMember(TimestampedModel):
    """A user's place in an organization. One row per pair, kept after leaving or removal;
    the only way back to ACTIVE is accepting a new invitation."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships"
    )
    role = models.CharField(max_length=10, choices=OrganizationRole.choices)
    status = models.CharField(
        max_length=8, choices=MembershipStatus.choices, default=MembershipStatus.ACTIVE
    )
    # Whether people outside the organization may see this membership.
    is_public = models.BooleanField(default=True)
    joined_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="organizations_member_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=OrganizationRole.values),
                name="organizations_member_role_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=MembershipStatus.values),
                name="organizations_member_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="organizations_member_user"),
            models.Index(
                fields=["organization", "status", "role"], name="organizations_member_org"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.organization_id} ({self.role}, {self.status})"


class OrganizationInvitation(TimestampedModel):
    """An offer of membership sent to an email address, which need not have an account yet.

    Only a hash of the emailed token is stored. The invitation can be answered once, by a
    signed-in user whose verified email is the invited address.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=OrganizationRole.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(
        max_length=8, choices=InvitationStatus.choices, default=InvitationStatus.PENDING
    )
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # At most one open invitation per address; settles concurrent duplicate invites.
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(status=InvitationStatus.PENDING),
                name="organizations_invitation_one_pending",
            ),
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")),
                name="organizations_invitation_email_lowercase",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=OrganizationRole.values),
                name="organizations_invitation_role_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=InvitationStatus.values),
                name="organizations_invitation_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["email", "status"], name="organizations_invitation_email"),
        ]

    def __str__(self) -> str:
        return f"invitation {self.pk} to {self.organization_id}"
