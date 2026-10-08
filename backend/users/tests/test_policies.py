import pytest

from users import policies
from users.models import PlatformRole, User, UserProfile


def profile_of(owner_id, visibility):
    return UserProfile(user_id=owner_id, visibility=visibility)


@pytest.mark.parametrize(
    ("visibility", "is_connection", "shares_community", "expected"),
    [
        ("PUBLIC", False, False, True),
        ("CONNECTIONS", False, False, False),
        ("CONNECTIONS", True, False, True),
        ("CONNECTIONS", False, True, False),
        ("COMMUNITY", False, False, False),
        ("COMMUNITY", False, True, True),
        ("COMMUNITY", True, False, True),
        ("PRIVATE", True, True, False),
    ],
)
def test_can_view_profile(visibility, is_connection, shares_community, expected):
    viewer = User(platform_role=PlatformRole.USER)
    owner = User()

    allowed = policies.can_view_profile(
        viewer,
        profile_of(owner.pk, visibility),
        is_connection=is_connection,
        shares_community=shares_community,
    )

    assert allowed is expected


def test_owner_and_staff_see_everything():
    owner = User()
    admin = User(platform_role=PlatformRole.ADMIN)
    profile = profile_of(owner.pk, "PRIVATE")
    profile.show_contact = profile.show_history = False

    for viewer in (owner, admin):
        assert policies.can_view_profile(
            viewer, profile, is_connection=False, shares_community=False
        )
        assert policies.can_view_contact(viewer, profile)
        assert policies.can_view_history(viewer, profile)
