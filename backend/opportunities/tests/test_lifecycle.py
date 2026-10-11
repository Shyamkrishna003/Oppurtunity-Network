"""The opportunity lifecycle, checked exhaustively: every pair of states, person and system."""

from itertools import product

import pytest
from rest_framework.exceptions import PermissionDenied

from common.errors import InvalidTransition
from opportunities import policies
from opportunities.models import Opportunity, OpportunityStatus
from opportunities.policies import LIFECYCLE, Manager
from organizations.models import OrganizationMember
from users.models import User

STATES = list(OpportunityStatus.values)
BOTH, PERSON, SYSTEM = {"manager", "system"}, {"manager"}, {"system"}

# Every legal move and who may make it. Nothing leaves ARCHIVED; nothing is ever reopened.
ALLOWED = {
    ("DRAFT", "PUBLISHED"): PERSON,
    ("PUBLISHED", "CLOSED"): PERSON,
    ("PUBLISHED", "EXPIRED"): SYSTEM,
    ("CLOSED", "ARCHIVED"): BOTH,
    ("EXPIRED", "ARCHIVED"): BOTH,
}


@pytest.mark.parametrize(
    ("source", "target", "actor"),
    [(s, t, a) for s, t, a in product(STATES, STATES, ("manager", "system")) if s != t],
)
def test_every_transition_for_person_and_system(source, target, actor):
    opportunity = Opportunity(status=source)
    acting = Manager(User()) if actor == "manager" else None

    if (source, target) not in ALLOWED:
        with pytest.raises(InvalidTransition):
            LIFECYCLE.apply(opportunity, target, actor=acting)
    elif actor in ALLOWED[(source, target)]:
        assert LIFECYCLE.apply(opportunity, target, actor=acting) is True
        assert opportunity.status == target
        return
    else:
        with pytest.raises(PermissionDenied):
            LIFECYCLE.apply(opportunity, target, actor=acting)
    assert opportunity.status == source


def test_archived_is_terminal_and_nothing_is_reopened():
    assert LIFECYCLE.is_terminal("ARCHIVED")
    for state in ("CLOSED", "EXPIRED", "ARCHIVED"):
        assert "PUBLISHED" not in LIFECYCLE.targets(state)
        assert "DRAFT" not in LIFECYCLE.targets(state)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("DRAFT", None),
        ("PUBLISHED", {"description", "deadline"}),
        ("CLOSED", set()),
        ("EXPIRED", set()),
        ("ARCHIVED", set()),
    ],
)
def test_editable_fields_shrink_as_the_opportunity_progresses(status, expected):
    assert policies.editable_fields(Opportunity(status=status)) == expected


def membership(user, organization_id, role, status="ACTIVE"):
    return OrganizationMember(user=user, organization_id=organization_id, role=role, status=status)


def test_a_personal_opportunity_is_managed_only_by_its_creator():
    creator, other = User(), User()
    opportunity = Opportunity(creator=creator)

    assert policies.can_manage(creator, opportunity, None)
    assert not policies.can_manage(other, opportunity, None)


@pytest.mark.parametrize(
    ("role", "status", "allowed"),
    [
        ("OWNER", "ACTIVE", True),
        ("ADMIN", "ACTIVE", True),
        ("RECRUITER", "ACTIVE", True),
        ("MEMBER", "ACTIVE", False),
        ("RECRUITER", "LEFT", False),
        ("OWNER", "REMOVED", False),
    ],
)
def test_an_organizations_opportunity_is_managed_by_its_posting_roles(role, status, allowed):
    user = User()
    organization_id = User().pk  # any UUID
    opportunity = Opportunity(creator=User(), organization_id=organization_id)

    held = membership(user, organization_id, role, status)

    assert policies.can_manage(user, opportunity, held) is allowed


def test_creating_an_organizations_opportunity_gives_no_lasting_claim_to_it():
    creator = User()
    organization_id, other_organization = User().pk, User().pk
    opportunity = Opportunity(creator=creator, organization_id=organization_id)

    # No membership any more, or a posting role in some other organization: neither counts.
    assert not policies.can_manage(creator, opportunity, None)
    elsewhere = membership(creator, other_organization, "OWNER")
    assert not policies.can_manage(creator, opportunity, elsewhere)
