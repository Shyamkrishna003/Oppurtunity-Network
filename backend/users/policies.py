"""Permission rules for user resources: pure functions of the actor and the object."""

from users.models import PlatformRole, ProfileVisibility, User, UserProfile


def is_platform_staff(user: User) -> bool:
    return user.platform_role in (PlatformRole.MODERATOR, PlatformRole.ADMIN)


def can_view_profile(
    viewer: User, profile: UserProfile, *, is_connection: bool, shares_community: bool
) -> bool:
    """Whether ``viewer`` may open the full profile. Blocks are checked by the selector."""
    if viewer.pk == profile.user_id or is_platform_staff(viewer):
        return True
    match profile.visibility:
        case ProfileVisibility.PUBLIC:
            return True
        case ProfileVisibility.CONNECTIONS:
            return is_connection
        case ProfileVisibility.COMMUNITY:
            return is_connection or shares_community
        case _:
            return False


def can_view_contact(viewer: User, profile: UserProfile) -> bool:
    return viewer.pk == profile.user_id or profile.show_contact or is_platform_staff(viewer)


def can_view_history(viewer: User, profile: UserProfile) -> bool:
    return viewer.pk == profile.user_id or profile.show_history or is_platform_staff(viewer)
