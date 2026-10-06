import uuid

import pytest
from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction

from users.models import PlatformRole, User
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_create_user_normalizes_email_and_hashes_password():
    user = User.objects.create_user("  Ada.Lovelace@Example.COM ", "correct-horse-battery")

    assert user.email == "ada.lovelace@example.com"
    assert user.password != "correct-horse-battery"
    assert user.check_password("correct-horse-battery")
    assert user.platform_role == PlatformRole.USER
    assert not user.is_staff
    assert not user.is_email_verified


def test_ids_are_time_ordered_uuids():
    first, second = UserFactory(), UserFactory()

    assert isinstance(first.id, uuid.UUID)
    assert first.id.version == 7
    assert first.id < second.id


def test_email_is_required():
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user("", "correct-horse-battery")


def test_create_superuser_is_a_platform_admin():
    admin = User.objects.create_superuser("root@example.com", "correct-horse-battery")

    assert admin.is_staff
    assert admin.is_superuser
    assert admin.platform_role == PlatformRole.ADMIN


def test_login_is_case_insensitive():
    UserFactory(email="ada@example.com")

    user = authenticate(username="ADA@Example.com", password="correct-horse-battery")

    assert user is not None
    assert user.email == "ada@example.com"


def test_emails_differing_only_by_case_cannot_coexist():
    UserFactory(email="ada@example.com")

    with pytest.raises(IntegrityError):
        User.objects.create_user("ADA@example.com", "correct-horse-battery")


def test_database_rejects_mixed_case_email_written_around_the_manager():
    with pytest.raises(IntegrityError, match="users_user_email_lowercase"), transaction.atomic():
        User.objects.bulk_create([User(email="Mixed@Example.com", password="!")])


def test_database_rejects_unknown_platform_role():
    with (
        pytest.raises(IntegrityError, match="users_user_platform_role_valid"),
        transaction.atomic(),
    ):
        User.objects.bulk_create([User(email="x@example.com", password="!", platform_role="GOD")])


def test_full_clean_lowercases_email():
    user = User(email="Grace@Example.com", password="!")

    user.full_clean()

    assert user.email == "grace@example.com"
