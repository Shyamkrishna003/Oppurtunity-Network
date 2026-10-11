"""Who may apply, who may see an application, and how one moves through the pipeline."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from applications.models import Application, ApplicationStatus
from common.state_machine import StateMachine, Transition
from jobs.models import ApplicationMethod
from opportunities.models import (
    ModerationStatus,
    Opportunity,
    OpportunityStatus,
    OpportunityType,
)

S = ApplicationStatus

# The stages in order. A manager may move an application to any later stage (skipping is
# normal: not every job has a screening call) but never back.
STAGES = (S.APPLIED, S.SCREENING, S.SHORTLISTED, S.INTERVIEW, S.OFFER, S.HIRED)
# Still being considered. Everything else is final.
OPEN = frozenset(STAGES[:-1])


@dataclass(frozen=True)
class Actor:
    """How the person acting relates to one application. Both can be true: someone who
    applied and later became a recruiter at the organization."""

    is_applicant: bool
    is_manager: bool


def decides(actor: Actor) -> bool:
    """Whether this person is on the employer's side of the application. Nobody decides on
    their own application, even if they have since joined the team that handles them."""
    return actor.is_manager and not actor.is_applicant


def _by_manager(actor: Actor | None, application: Application) -> bool:
    return actor is not None and decides(actor)


def _by_applicant(actor: Actor | None, application: Application) -> bool:
    return actor is not None and actor.is_applicant


PIPELINE = StateMachine(
    "application",
    [
        *(
            Transition(source, target, policy=_by_manager)
            for index, source in enumerate(STAGES)
            for target in STAGES[index + 1 :]
        ),
        *(Transition(source, S.REJECTED, policy=_by_manager) for source in STAGES[:-1]),
        # Only the applicant withdraws; a manager who wants to stop rejects instead.
        *(Transition(source, S.WITHDRAWN, policy=_by_applicant) for source in STAGES[:-1]),
    ],
)


def can_view(actor: Actor) -> bool:
    return actor.is_applicant or actor.is_manager


def next_statuses(actor: Actor, application: Application) -> list[ApplicationStatus]:
    """Where this person may move the application now: the later stages in order, then
    rejection. Empty for the applicant (who withdraws instead) and once it is decided."""
    if not decides(actor) or application.status not in OPEN:
        return []
    later = STAGES[STAGES.index(ApplicationStatus(application.status)) + 1 :]
    return [*later, S.REJECTED]


def can_withdraw(actor: Actor, application: Application) -> bool:
    return actor.is_applicant and application.status in OPEN


def can_download_resume(actor: Actor, application: Application) -> bool:
    """The applicant always; the job's managers until the application is withdrawn. Taking
    an application back takes the resume back with it."""
    return actor.is_applicant or (actor.is_manager and application.status != S.WITHDRAWN)


def can_read_notes(actor: Actor) -> bool:
    """Notes written with a move are for the people deciding, never for the applicant."""
    return decides(actor)


class Barrier(StrEnum):
    """Why someone cannot apply to a job. The value is the error code the API answers with."""

    NOT_ACCEPTING = "not_accepting"
    EXTERNAL = "external_application"
    OWN_JOB = "own_job"


BARRIER_MESSAGES = {
    Barrier.NOT_ACCEPTING: "This job is no longer taking applications.",
    Barrier.EXTERNAL: "Applications for this job are taken on another website.",
    Barrier.OWN_JOB: "You manage this job, so you cannot apply to it.",
}


def barrier_to_applying(
    opportunity: Opportunity, *, is_manager: bool, is_blocked: bool, now: datetime
) -> Barrier | None:
    """What stops this person applying, if anything. The opportunity is a job they can see.

    ``is_blocked``: the job is a personal one and its poster and this person have blocked
    one another. It is reported exactly like a closed job, so a block is not revealed.
    """
    if opportunity.type != OpportunityType.JOB:
        raise ValueError("Only jobs take applications.")
    if is_manager:
        return Barrier.OWN_JOB
    if (
        opportunity.status != OpportunityStatus.PUBLISHED
        or opportunity.moderation_status != ModerationStatus.VISIBLE
        or (opportunity.deadline is not None and opportunity.deadline <= now)
        or is_blocked
    ):
        return Barrier.NOT_ACCEPTING
    if opportunity.job.application_method != ApplicationMethod.INTERNAL:
        return Barrier.EXTERNAL
    return None
