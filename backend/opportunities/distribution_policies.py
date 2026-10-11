"""Rules for sharing an opportunity with a community.

Two parties are involved and each owns one side. The opportunity's manager decides to offer
it; the community decides whether to show it. One community's decision never affects another
community or the opportunity itself.
"""

from dataclasses import dataclass

from common.state_machine import StateMachine, Transition
from communities.models import Community, CommunityRole, PostingPolicy
from communities.policies import Actor as CommunityActor
from communities.policies import can_manage, can_review_requests, is_member
from opportunities.models import DistributionStatus, OpportunityCommunity

S = DistributionStatus


def can_review(actor: CommunityActor) -> bool:
    """Moderators, admins and owners decide what their community shows."""
    return can_review_requests(actor)


def share_outcome(community: Community, actor: CommunityActor) -> DistributionStatus | None:
    """What sharing into ``community`` would lead to for this person: shown at once, queued
    for review, or (``None``) not allowed at all.

    Someone who could approve the share themselves is not made to wait for a review.
    """
    if not is_member(actor):
        return None
    if can_review(actor):
        return S.APPROVED if _may_post(community, actor) else None
    if community.posting_policy == PostingPolicy.MEMBERS_AUTO:
        return S.APPROVED
    if community.posting_policy == PostingPolicy.MEMBERS_WITH_APPROVAL:
        return S.PENDING
    return None


def _may_post(community: Community, actor: CommunityActor) -> bool:
    # "Admins only" excludes moderators: they review what others share, but do not post.
    if community.posting_policy == PostingPolicy.ADMINS_ONLY:
        return can_manage(actor)
    return True


@dataclass(frozen=True)
class Reviewer:
    """A community moderator, admin or owner acting on a share."""

    role: CommunityRole


@dataclass(frozen=True)
class Submitter:
    """A manager of the opportunity acting on their own share."""


Party = Reviewer | Submitter


def _by_reviewer(actor: Party, share: OpportunityCommunity) -> bool:
    return isinstance(actor, Reviewer)


def _by_submitter(actor: Party, share: OpportunityCommunity) -> bool:
    return isinstance(actor, Submitter)


# The service establishes who the actor is (a reviewer of that community, or a manager of
# that opportunity) before building a Reviewer or Submitter.
DISTRIBUTION = StateMachine(
    "community share",
    [
        Transition(S.PENDING, S.APPROVED, policy=_by_reviewer),
        Transition(S.PENDING, S.REJECTED, policy=_by_reviewer),
        Transition(S.APPROVED, S.REMOVED, policy=_by_reviewer),
        # A rejected share may be offered again, for instance after the job was reworded.
        # A removed one may not: the community has taken it down.
        Transition(S.REJECTED, S.PENDING, policy=_by_submitter),
        # Either party can get here: a reviewer who reconsiders, or a submitter whose
        # resubmission needs no review (the service decides that, never the request).
        Transition(S.REJECTED, S.APPROVED),
    ],
)
