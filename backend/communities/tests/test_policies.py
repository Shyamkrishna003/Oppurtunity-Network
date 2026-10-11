"""The membership state machine, checked exhaustively: every pair of states, every actor."""

import uuid
from itertools import product

import pytest
from rest_framework.exceptions import PermissionDenied

from common.errors import InvalidTransition
from communities import policies
from communities.models import CommunityMember, MemberStatus
from communities.policies import MEMBERSHIP, Actor

STATES = list(MemberStatus.values)
FORMER = ("LEFT", "REJECTED", "REMOVED")
SELF, MANAGERS, REVIEWERS = {"self"}, {"admin", "owner"}, {"moderator", "admin", "owner"}

# Every legal transition and exactly who may make it, for an ordinary member as the target.
ALLOWED = {
    ("PENDING", "ACTIVE"): REVIEWERS,
    ("PENDING", "REJECTED"): MANAGERS,
    ("PENDING", "LEFT"): SELF,
    ("INVITED", "ACTIVE"): SELF,
    ("INVITED", "LEFT"): SELF,
    ("INVITED", "REMOVED"): MANAGERS,
    ("ACTIVE", "LEFT"): SELF,
    ("ACTIVE", "REMOVED"): MANAGERS,
    ("ACTIVE", "BANNED"): MANAGERS,
    **{(former, "ACTIVE"): SELF for former in FORMER},
    **{(former, "PENDING"): SELF for former in FORMER},
    **{(former, "INVITED"): MANAGERS for former in FORMER},
    ("BANNED", "REMOVED"): MANAGERS,
}
ACTORS = ("self", "outsider", "member", "moderator", "admin", "owner")


def make_actor(kind, target):
    if kind == "self":
        return Actor(target.user_id, None)
    role = None if kind == "outsider" else kind.upper()
    return Actor(uuid.uuid4(), role)


def member(status, role="MEMBER"):
    return CommunityMember(user_id=uuid.uuid4(), status=status, role=role)


@pytest.mark.parametrize(
    ("source", "target", "actor"),
    [(s, t, a) for s, t, a in product(STATES, STATES, ACTORS) if s != t],
)
def test_every_transition_for_every_actor(source, target, actor):
    subject = member(source)
    acting = make_actor(actor, subject)

    if (source, target) not in ALLOWED:
        with pytest.raises(InvalidTransition):
            MEMBERSHIP.apply(subject, target, actor=acting)
    elif actor in ALLOWED[(source, target)]:
        assert MEMBERSHIP.apply(subject, target, actor=acting) is True
        assert subject.status == target
    else:
        with pytest.raises(PermissionDenied):
            MEMBERSHIP.apply(subject, target, actor=acting)
    if (source, target) not in ALLOWED or actor not in ALLOWED[(source, target)]:
        assert subject.status == source


def test_a_ban_cannot_be_escaped_by_the_banned_person():
    banned = member("BANNED")

    for target in ("ACTIVE", "PENDING", "LEFT", "INVITED"):
        with pytest.raises(InvalidTransition):
            MEMBERSHIP.apply(banned, target, actor=Actor(banned.user_id, None))


@pytest.mark.parametrize(
    ("actor_role", "target_role", "allowed"),
    [
        ("OWNER", "OWNER", True),
        ("OWNER", "ADMIN", True),
        ("OWNER", "MEMBER", True),
        ("ADMIN", "MODERATOR", True),
        ("ADMIN", "MEMBER", True),
        ("ADMIN", "ADMIN", False),
        ("ADMIN", "OWNER", False),
        ("MODERATOR", "MEMBER", False),
        ("MEMBER", "MEMBER", False),
    ],
)
@pytest.mark.parametrize("target", ["REMOVED", "BANNED"])
def test_removing_and_banning_require_outranking_the_member(
    actor_role, target_role, allowed, target
):
    subject = member("ACTIVE", target_role)
    acting = Actor(uuid.uuid4(), actor_role)

    if allowed:
        assert MEMBERSHIP.apply(subject, target, actor=acting)
    else:
        with pytest.raises(PermissionDenied):
            MEMBERSHIP.apply(subject, target, actor=acting)


def test_a_manager_cannot_remove_or_ban_themselves():
    owner = member("ACTIVE", "OWNER")

    for target in ("REMOVED", "BANNED"):
        with pytest.raises(PermissionDenied):
            MEMBERSHIP.apply(owner, target, actor=Actor(owner.user_id, "OWNER"))


@pytest.mark.parametrize(
    ("actor_role", "target_role", "new_role", "allowed"),
    [
        ("OWNER", "MEMBER", "OWNER", True),
        ("OWNER", "ADMIN", "MEMBER", True),
        ("ADMIN", "MEMBER", "MODERATOR", True),
        ("ADMIN", "MODERATOR", "MEMBER", True),
        ("ADMIN", "MEMBER", "ADMIN", False),
        ("ADMIN", "ADMIN", "MEMBER", False),
        ("ADMIN", "OWNER", "MEMBER", False),
        ("MODERATOR", "MEMBER", "MODERATOR", False),
        (None, "MEMBER", "MODERATOR", False),
    ],
)
def test_who_may_change_which_role(actor_role, target_role, new_role, allowed):
    subject = member("ACTIVE", target_role)

    assert policies.can_change_role(Actor(uuid.uuid4(), actor_role), subject, new_role) is allowed


def test_roles_change_only_on_active_members_and_never_ones_own():
    owner = Actor(uuid.uuid4(), "OWNER")
    invited = member("INVITED")
    themselves = CommunityMember(user_id=owner.user_id, status="ACTIVE", role="OWNER")

    assert not policies.can_change_role(owner, invited, "ADMIN")
    assert not policies.can_change_role(owner, themselves, "ADMIN")


def test_only_active_memberships_give_an_actor_a_role():
    user_id = uuid.uuid4()

    assert policies.actor_for(user_id, None).role is None
    for status in STATES:
        row = CommunityMember(user_id=user_id, status=status, role="MEMBER")
        assert (policies.actor_for(user_id, row).role is not None) == (status == "ACTIVE")
