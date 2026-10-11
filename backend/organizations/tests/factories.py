from django.utils import timezone
from factory.declarations import LazyFunction, Sequence, SubFactory
from factory.django import DjangoModelFactory

from organizations.models import Organization, OrganizationMember, OrganizationRole
from users.tests.factories import UserFactory


class OrganizationFactory(DjangoModelFactory[Organization]):
    class Meta:
        model = Organization

    name = Sequence(lambda n: f"Organization {n}")
    slug = Sequence(lambda n: f"organization-{n}")


class MemberFactory(DjangoModelFactory[OrganizationMember]):
    class Meta:
        model = OrganizationMember

    organization = SubFactory(OrganizationFactory)
    user = SubFactory(UserFactory)
    role = OrganizationRole.MEMBER
    joined_at = LazyFunction(timezone.now)


def organization_with_roles(*roles: str):
    """An organization with one member per requested role, plus an owner.

    Returns ``(organization, members)`` where ``members`` maps each role name to its
    membership; ``"OWNER"`` is always present.
    """
    organization = OrganizationFactory()
    members = {
        role: MemberFactory(organization=organization, role=role) for role in {"OWNER", *roles}
    }
    return organization, members
