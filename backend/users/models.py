import uuid
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.postgres.indexes import GinIndex
from django.db import models, transaction
from django.db.models.functions import Lower, Upper

from common.choices import ExperienceLevel, WorkMode
from common.models import TimestampedModel, UUIDModel


class PlatformRole(models.TextChoices):
    USER = "USER", "User"
    MODERATOR = "MODERATOR", "Moderator"
    ADMIN = "ADMIN", "Admin"


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        # Stricter than Django's default (which keeps the local part's case):
        # addresses are compared case-insensitively everywhere on the platform.
        return (email or "").strip().lower()

    def _create(self, email: str, password: str | None, **extra_fields: Any) -> User:
        email = self.normalize_email(email)
        if not email:
            raise ValueError("An email address is required.")
        display_name = extra_fields.pop("display_name", "") or email.split("@")[0]
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        # Every user has a profile; creating both together keeps that an invariant.
        with transaction.atomic(using=self._db):
            user.save(using=self._db)
            UserProfile.objects.using(self._db).create(user=user, display_name=display_name[:80])
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> User:
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("platform_role", PlatformRole.ADMIN)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create(email, password, **extra_fields)

    def get_by_natural_key(self, email: str | None) -> User:
        return self.get(email=self.normalize_email(email))


class User(TimestampedModel, AbstractBaseUser, PermissionsMixin):
    """Login identity. Profile data lives in a separate one-to-one model."""

    email = models.EmailField(unique=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    platform_role = models.CharField(
        max_length=16, choices=PlatformRole.choices, default=PlatformRole.USER
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        constraints = [
            # With the unique index on email this gives case-insensitive uniqueness.
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")), name="users_user_email_lowercase"
            ),
            models.CheckConstraint(
                condition=models.Q(platform_role__in=PlatformRole.values),
                name="users_user_platform_role_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    def clean(self) -> None:
        super().clean()
        self.email = UserManager.normalize_email(self.email)

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None


class ProfileVisibility(models.TextChoices):
    PUBLIC = "PUBLIC", "Public"
    CONNECTIONS = "CONNECTIONS", "Connections only"
    COMMUNITY = "COMMUNITY", "Community members"
    PRIVATE = "PRIVATE", "Private"


class UserProfile(models.Model):
    """What other people see about a user, subject to ``visibility`` and the section flags."""

    user = models.OneToOneField(
        User, primary_key=True, on_delete=models.CASCADE, related_name="profile"
    )
    display_name = models.CharField(max_length=80)
    headline = models.CharField(max_length=140, blank=True)
    bio = models.TextField(max_length=2000, blank=True)
    # Storage key of the re-encoded image; never a client-supplied filename.
    avatar = models.CharField(max_length=255, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    region = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    work_mode_preference = models.CharField(max_length=8, choices=WorkMode.choices, blank=True)
    experience_level = models.CharField(max_length=8, choices=ExperienceLevel.choices, blank=True)
    visibility = models.CharField(
        max_length=12, choices=ProfileVisibility.choices, default=ProfileVisibility.PUBLIC
    )
    # Section flags apply to viewers other than the owner who may see the profile at all.
    show_contact = models.BooleanField(default=False)
    show_history = models.BooleanField(default=True)
    accepts_referral_requests = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(visibility__in=ProfileVisibility.values),
                name="users_userprofile_visibility_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(work_mode_preference__in=["", *WorkMode.values]),
                name="users_userprofile_work_mode_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(experience_level__in=["", *ExperienceLevel.values]),
                name="users_userprofile_experience_level_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(country_code=Upper("country_code")),
                name="users_userprofile_country_code_uppercase",
            ),
        ]
        indexes = [
            GinIndex(
                fields=["display_name"],
                opclasses=["gin_trgm_ops"],
                name="users_profile_name_trgm",
            ),
            models.Index(fields=["country_code", "city"], name="users_profile_location"),
        ]

    def __str__(self) -> str:
        return self.display_name


class SkillKind(models.TextChoices):
    HAS = "HAS", "Has"
    INTERESTED = "INTERESTED", "Interested in"


class UserSkill(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_skills")
    skill = models.ForeignKey("taxonomy.Skill", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=10, choices=SkillKind.choices)

    class Meta:
        constraints = [
            # Column order also serves the "skills of this user, by kind" lookup.
            models.UniqueConstraint(
                fields=["user", "kind", "skill"], name="users_userskill_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=SkillKind.values), name="users_userskill_kind_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.kind} {self.skill_id}"


class UserExperience(TimestampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="experiences")
    title = models.CharField(max_length=120)
    organization_name = models.CharField(max_length=120)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    description = models.TextField(max_length=2000, blank=True)

    class Meta:
        ordering = ("-start_date", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="users_userexperience_dates_ordered",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} at {self.organization_name}"


class UserEducation(TimestampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="educations")
    institution = models.CharField(max_length=160)
    degree = models.CharField(max_length=120, blank=True)
    field_of_study = models.CharField(max_length=120, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("-start_date", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="users_usereducation_dates_ordered",
            ),
        ]

    def __str__(self) -> str:
        return self.institution


class UserBlock(UUIDModel):
    """Directional: ``blocker`` no longer sees or is seen by ``blocked``."""

    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocks_made")
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocks_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="users_userblock_unique"),
            models.CheckConstraint(
                condition=~models.Q(blocker=models.F("blocked")), name="users_userblock_not_self"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.blocker_id} blocks {self.blocked_id}"


class RefreshToken(UUIDModel):
    """One link in a rotation chain. Only a hash of the token is stored.

    All tokens descended from one login share ``family``; presenting an already rotated
    token (outside a short grace window) revokes the whole family.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    family = models.UUIDField(default=uuid.uuid4)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    rotated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["family"], name="users_refresh_family"),
            models.Index(fields=["user", "revoked_at"], name="users_refresh_user"),
            models.Index(fields=["expires_at"], name="users_refresh_expires"),
        ]

    def __str__(self) -> str:
        return f"refresh token {self.pk}"
