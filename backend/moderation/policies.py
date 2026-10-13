"""Who may moderate, how a report moves, and what can be done to each kind of target."""

from dataclasses import dataclass

from common.state_machine import StateMachine, Transition
from moderation.models import ActionType, Report, ReportStatus, TargetType
from opportunities.models import ModerationStatus
from users.models import User
from users.policies import is_platform_staff

S = ReportStatus
# Still waiting for a decision.
IN_PROGRESS = frozenset({S.OPEN, S.UNDER_REVIEW})


def can_moderate(user: User) -> bool:
    """Platform moderators and admins. Roles inside an organization or a community give
    nothing here."""
    return user.is_active and is_platform_staff(user)


@dataclass(frozen=True)
class Moderator:
    user: User


def _uninvolved(actor: Moderator | None, report: Report) -> bool:
    """A moderator does not decide a report they filed, or one about themselves."""
    if actor is None:
        return False
    involved = {report.reporter_id}
    if report.target_type == TargetType.USER and report.target_user_id is not None:
        involved.add(report.target_user_id)
    return actor.user.pk not in involved


REPORT = StateMachine(
    "report",
    [
        Transition(S.OPEN, S.UNDER_REVIEW, policy=_uninvolved),
        *(
            Transition(source, target, policy=_uninvolved)
            for source in sorted(IN_PROGRESS)
            for target in (S.ACTION_TAKEN, S.DISMISSED)
        ),
    ],
)

# What a moderator can do to each kind of target. Actions on people, organizations and
# communities are added here as they are built.
ACTIONS_FOR: dict[TargetType, frozenset[ActionType]] = {
    TargetType.USER: frozenset(),
    TargetType.ORGANIZATION: frozenset(),
    TargetType.COMMUNITY: frozenset(),
    TargetType.OPPORTUNITY: frozenset({ActionType.HIDE, ActionType.REMOVE, ActionType.RESTORE}),
}

# Actions that settle a report. Putting something back is not an answer to a complaint.
RESOLVING = frozenset({ActionType.HIDE, ActionType.REMOVE})

# For an opportunity: the state each action leaves it in, and the states it can be taken
# from. Removing is final; only hiding can be undone.
OPPORTUNITY_OUTCOME = {
    ActionType.HIDE: ModerationStatus.HIDDEN,
    ActionType.REMOVE: ModerationStatus.REMOVED,
    ActionType.RESTORE: ModerationStatus.VISIBLE,
}
OPPORTUNITY_ALLOWED_FROM = {
    ActionType.HIDE: frozenset({ModerationStatus.VISIBLE}),
    ActionType.REMOVE: frozenset({ModerationStatus.VISIBLE, ModerationStatus.HIDDEN}),
    ActionType.RESTORE: frozenset({ModerationStatus.HIDDEN}),
}
