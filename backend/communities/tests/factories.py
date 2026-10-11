from django.utils import timezone
from factory.declarations import LazyAttribute, Sequence, SubFactory
from factory.django import DjangoModelFactory

from communities.models import Community, CommunityMember, CommunityRole, MemberStatus
from users.tests.factories import UserFactory


class CommunityFactory(DjangoModelFactory[Community]):
    class Meta:
        model = Community

    name = Sequence(lambda n: f"Community {n}")
    slug = Sequence(lambda n: f"community-{n}")


class CommunityMemberFactory(DjangoModelFactory[CommunityMember]):
    class Meta:
        model = CommunityMember

    community = SubFactory(CommunityFactory)
    user = SubFactory(UserFactory)
    role = CommunityRole.MEMBER
    status = MemberStatus.ACTIVE
    joined_at = LazyAttribute(lambda m: timezone.now() if m.status == "ACTIVE" else None)


def community_with_roles(*roles: str, **community_fields):
    """A community with one active member per requested role, plus an owner.

    Returns ``(community, members)`` where ``members`` maps each role name to its membership;
    ``"OWNER"`` is always present.
    """
    community = CommunityFactory(**community_fields)
    members = {
        role: CommunityMemberFactory(community=community, role=role) for role in {"OWNER", *roles}
    }
    return community, members
