"""Read queries for user resources. Views load objects only through these."""

from uuid import UUID

from django.db.models import Q
from django.http import Http404

from taxonomy.models import Skill
from users import policies
from users.models import SkillKind, User, UserBlock, UserSkill


def is_blocked_either_way(a: User, b: User) -> bool:
    return UserBlock.objects.filter(Q(blocker=a, blocked=b) | Q(blocker=b, blocked=a)).exists()


def get_visible_user(viewer: User, user_id: UUID) -> User:
    """Return the user whose profile ``viewer`` may open, or raise 404.

    A hidden, blocked, deactivated and non-existent profile all look the same to the caller.
    """
    user = User.objects.select_related("profile").filter(pk=user_id, is_active=True).first()
    if user is None:
        raise Http404
    if user.pk != viewer.pk and is_blocked_either_way(viewer, user):
        raise Http404
    # Connections and communities do not exist yet, so "connections only" and "community
    # members" profiles are visible to their owner and platform staff alone for now.
    if not policies.can_view_profile(
        viewer, user.profile, is_connection=False, shares_community=False
    ):
        raise Http404
    return user


def skills_by_kind(user: User) -> dict[str, list[Skill]]:
    grouped: dict[str, list[Skill]] = {kind: [] for kind in SkillKind.values}
    rows = UserSkill.objects.filter(user=user).select_related("skill").order_by("skill__name")
    for row in rows:
        grouped[row.kind].append(row.skill)
    return grouped
