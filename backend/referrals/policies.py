"""Who may ask for a referral, who may see one, and how one moves."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from applications.models import ApplicationStatus
from common.state_machine import StateMachine, Transition
from jobs.models import ApplicationMethod
from opportunities.models import (
    ModerationStatus,
    Opportunity,
    OpportunityStatus,
    OpportunityType,
)
from referrals.models import ReferralRequest, ReferralStatus

S = ReferralStatus

# After the referral is made, in order. These only ever follow the requester's application.
TRACKED = (S.REFERRED, S.APPLICATION_SUBMITTED, S.INTERVIEW, S.OFFER, S.JOINED)
# Still going somewhere. Everything else is final.
OPEN = frozenset({S.REQUESTED, S.ACCEPTED, *TRACKED[:-1]})
# How many referrers one person may be asking, or working with, for one job at a time.
MAX_OPEN_PER_JOB = 3

# Where a referral stands for each state of the application it follows. Before the
# interview the referrer is told only that an application exists, not how far it got.
MIRROR: dict[str, ReferralStatus] = {
    ApplicationStatus.APPLIED: S.APPLICATION_SUBMITTED,
    ApplicationStatus.SCREENING: S.APPLICATION_SUBMITTED,
    ApplicationStatus.SHORTLISTED: S.APPLICATION_SUBMITTED,
    ApplicationStatus.INTERVIEW: S.INTERVIEW,
    ApplicationStatus.OFFER: S.OFFER,
    ApplicationStatus.HIRED: S.JOINED,
    ApplicationStatus.REJECTED: S.CLOSED,
    ApplicationStatus.WITHDRAWN: S.CLOSED,
}


@dataclass(frozen=True)
class Actor:
    """How the person acting relates to one referral. The system acts as ``None``."""

    is_requester: bool
    is_referrer: bool
    # Manages the job the referral is for. Sees it once made; never moves it.
    is_manager: bool = False


def _by_referrer(actor: Actor | None, referral: ReferralRequest) -> bool:
    return actor is not None and actor.is_referrer


def _by_requester(actor: Actor | None, referral: ReferralRequest) -> bool:
    return actor is not None and actor.is_requester


def _by_system(actor: Actor | None, referral: ReferralRequest) -> bool:
    return actor is None


def _by_referrer_or_system(actor: Actor | None, referral: ReferralRequest) -> bool:
    return actor is None or actor.is_referrer


WORKFLOW = StateMachine(
    "referral",
    [
        Transition(S.REQUESTED, S.ACCEPTED, policy=_by_referrer),
        Transition(S.REQUESTED, S.DECLINED, policy=_by_referrer),
        Transition(S.REQUESTED, S.CANCELLED, policy=_by_requester),
        Transition(S.REQUESTED, S.EXPIRED, policy=_by_system),
        Transition(S.ACCEPTED, S.REFERRED, policy=_by_referrer),
        # Nobody but the system moves a referral once it has been made.
        *(
            Transition(source, target, policy=_by_system)
            for index, source in enumerate(TRACKED)
            for target in TRACKED[index + 1 :]
        ),
        # The job stopped taking applications, or the application ended.
        Transition(S.REQUESTED, S.CLOSED, policy=_by_system),
        *(Transition(source, S.CLOSED, policy=_by_system) for source in TRACKED[:-1]),
        # Someone who agreed to refer may still change their mind before doing it.
        Transition(S.ACCEPTED, S.CLOSED, policy=_by_referrer_or_system),
    ],
)


def is_visible_to_managers(referral: ReferralRequest) -> bool:
    """The people hiring see a referral from the moment it is made, and not before: who
    asked whom, and who said no, is between the two of them."""
    return referral.referred_at is not None


def can_view(actor: Actor, referral: ReferralRequest) -> bool:
    return (
        actor.is_requester
        or actor.is_referrer
        or (actor.is_manager and is_visible_to_managers(referral))
    )


def can_read_message(actor: Actor) -> bool:
    return actor.is_requester or actor.is_referrer


def can_read_endorsement(actor: Actor) -> bool:
    """What the referrer told the employer about the requester is not for the requester."""
    return actor.is_referrer or (actor.is_manager and not actor.is_requester)


def actions(actor: Actor, referral: ReferralRequest) -> list[str]:
    """What this person may do with the referral now, in the order to offer it."""
    if referral.status == S.REQUESTED:
        if actor.is_referrer:
            return ["accept", "decline"]
        if actor.is_requester:
            return ["cancel"]
    if referral.status == S.ACCEPTED and actor.is_referrer:
        return ["refer", "back_out"]
    return []


class Barrier(StrEnum):
    """Why someone cannot ask for a referral to a job. The value is the API's error code."""

    NOT_ACCEPTING = "not_accepting"
    NO_REFERRALS = "referrals_unavailable"
    OWN_JOB = "own_job"
    APPLICATION_ENDED = "application_ended"


BARRIER_MESSAGES = {
    Barrier.NOT_ACCEPTING: "This job is no longer taking applications.",
    Barrier.NO_REFERRALS: "Referrals are not available for this job.",
    Barrier.OWN_JOB: "You manage this job, so you cannot ask to be referred to it.",
    Barrier.APPLICATION_ENDED: "Your application to this job has already ended.",
}


def barrier_to_requesting(
    opportunity: Opportunity, *, is_manager: bool, application_status: str | None, now: datetime
) -> Barrier | None:
    """What stops this person asking for a referral, if anything. The opportunity is one
    they can see; ``application_status`` is that of their own application to it, if any.

    Referrals exist only for an organization's jobs that are applied to on the platform:
    a referrer vouches as a member of the organization, and the outcome has to be tracked.
    """
    if (
        opportunity.type != OpportunityType.JOB
        or opportunity.organization_id is None
        or opportunity.job.application_method != ApplicationMethod.INTERNAL
    ):
        return Barrier.NO_REFERRALS
    if is_manager:
        return Barrier.OWN_JOB
    if (
        opportunity.status != OpportunityStatus.PUBLISHED
        or opportunity.moderation_status != ModerationStatus.VISIBLE
        or (opportunity.deadline is not None and opportunity.deadline <= now)
    ):
        return Barrier.NOT_ACCEPTING
    if application_status is not None and MIRROR[application_status] in (S.CLOSED, S.JOINED):
        return Barrier.APPLICATION_ENDED
    return None
