from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower

from common.models import TimestampedModel


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
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
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
