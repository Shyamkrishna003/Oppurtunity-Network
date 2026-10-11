"""Who may share into a community, and the share state machine, checked exhaustively."""

import uuid
from itertools import product

import pytest
from rest_framework.exceptions import PermissionDenied

from common.errors import InvalidTransition
from communities.models import Community
from communities.policies import Actor
from opportunities.distribution_policies import (
    DISTRIBUTION,
    Reviewer,
    Submitter,
    can_review,
    share_outcome,
)
from opportunities.models import DistributionStatus, OpportunityCommunity

STATES = list(DistributionStatus.values)


@pytest.mark.parametrize(
    ("posting_policy", "role", "outcome"),
    [
        # Admins only: moderators review, but do not post.
        ("ADMINS_ONLY", "OWNER", "APPROVED"),
        ("ADMINS_ONLY", "ADMIN", "APPROVED"),
        ("ADMINS_ONLY", "MODERATOR", None),
        ("ADMINS_ONLY", "MEMBER", None),
        # Review required: those who could approve it themselves are not made to wait.
        ("MEMBERS_WITH_APPROVAL", "OWNER", "APPROVED"),
        ("MEMBERS_WITH_APPROVAL", "ADMIN", "APPROVED"),
        ("MEMBERS_WITH_APPROVAL", "MODERATOR", "APPROVED"),
        ("MEMBERS_WITH_APPROVAL", "MEMBER", "PENDING"),
        ("MEMBERS_AUTO", "OWNER", "APPROVED"),
        ("MEMBERS_AUTO", "MODERATOR", "APPROVED"),
        ("MEMBERS_AUTO", "MEMBER", "APPROVED"),
        # Not an active member: never.
        ("ADMINS_ONLY", None, None),
        ("MEMBERS_WITH_APPROVAL", None, None),
        ("MEMBERS_AUTO", None, None),
    ],
)
def test_what_sharing_leads_to(posting_policy, role, outcome):
    community = Community(posting_policy=posting_policy)

    assert share_outcome(community, Actor(uuid.uuid4(), role)) == outcome


@pytest.mark.parametrize(
    ("role", "allowed"),
    [("OWNER", True), ("ADMIN", True), ("MODERATOR", True), ("MEMBER", False), (None, False)],
)
def test_who_reviews_what_a_community_shows(role, allowed):
    assert can_review(Actor(uuid.uuid4(), role)) is allowed


REVIEWER, SUBMITTER = {"reviewer"}, {"submitter"}
# Every legal move and who makes it. A removed share is final.
ALLOWED = {
    ("PENDING", "APPROVED"): REVIEWER,
    ("PENDING", "REJECTED"): REVIEWER,
    ("APPROVED", "REMOVED"): REVIEWER,
    ("REJECTED", "PENDING"): SUBMITTER,
    ("REJECTED", "APPROVED"): REVIEWER | SUBMITTER,
}


@pytest.mark.parametrize(
    ("source", "target", "party"),
    [(s, t, p) for s, t, p in product(STATES, STATES, ("reviewer", "submitter")) if s != t],
)
def test_every_share_transition_for_both_parties(source, target, party):
    share = OpportunityCommunity(status=source)
    actor = Reviewer("MODERATOR") if party == "reviewer" else Submitter()

    if (source, target) not in ALLOWED:
        with pytest.raises(InvalidTransition):
            DISTRIBUTION.apply(share, target, actor=actor)
    elif party in ALLOWED[(source, target)]:
        assert DISTRIBUTION.apply(share, target, actor=actor) is True
        assert share.status == target
        return
    else:
        with pytest.raises(PermissionDenied):
            DISTRIBUTION.apply(share, target, actor=actor)
    assert share.status == source


def test_a_removed_share_is_final_and_a_submitter_cannot_approve_a_pending_one():
    assert DISTRIBUTION.is_terminal("REMOVED")
    with pytest.raises(PermissionDenied):
        DISTRIBUTION.apply(OpportunityCommunity(status="PENDING"), "APPROVED", actor=Submitter())
