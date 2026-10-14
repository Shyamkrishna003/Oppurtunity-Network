"""Who may moderate, how a report moves, and what can be done to each kind of target."""

from dataclasses import dataclass

from django.db import models

from common.state_machine import StateMachine, Transition
from communities.models import Community, CommunityStatus
from moderation.models import ActionType, Report, ReportStatus, TargetType
from opportunities.models import ModerationStatus, Opportunity
from organizations.models import Organization, OrganizationStatus, VerificationStatus
from users.models import PlatformRole, User
from users.policies import is_platform_staff

S = ReportStatus
A = ActionType
# Still waiting for a decision.
IN_PROGRESS = frozenset({S.OPEN, S.UNDER_REVIEW})


def can_moderate(user: User) -> bool:
    """Platform moderators and admins. Roles inside an organization or a community give
    nothing here."""
    return user.is_active and is_platform_staff(user)


def is_admin(user: User) -> bool:
    return user.is_active and user.platform_role == PlatformRole.ADMIN


@dataclass(frozen=True)
class Moderator:
    """Someone with authority over a report: a platform moderator, or a moderator of the
    community the report was sent to."""

    user: User
    # Whether they manage what was reported. Platform staff are trusted past this; a
    # community's moderators are its members, and often the ones who posted.
    manages_target: bool = False


def uninvolved(actor: Moderator | None, report: Report) -> bool:
    """A moderator does not decide a report they filed, one about themselves, or one about
    something that is theirs."""
    if actor is None or actor.manages_target:
        return False
    involved = {report.reporter_id}
    if report.target_type == TargetType.USER and report.target_user_id is not None:
        involved.add(report.target_user_id)
    return actor.user.pk not in involved


REPORT = StateMachine(
    "report",
    [
        Transition(S.OPEN, S.UNDER_REVIEW, policy=uninvolved),
        # Handed on: a community's moderators passing a report up to the platform's.
        Transition(S.UNDER_REVIEW, S.OPEN, policy=uninvolved),
        *(
            Transition(source, target, policy=uninvolved)
            for source in sorted(IN_PROGRESS)
            for target in (S.ACTION_TAKEN, S.DISMISSED)
        ),
    ],
)

# What exists for each kind of target, whatever its present state.
ACTIONS_FOR: dict[TargetType, frozenset[ActionType]] = {
    TargetType.USER: frozenset(
        {A.WARN, A.RESTRICT_POSTING, A.UNRESTRICT_POSTING, A.SUSPEND, A.UNSUSPEND}
    ),
    TargetType.ORGANIZATION: frozenset({A.VERIFY, A.UNVERIFY, A.SUSPEND, A.UNSUSPEND}),
    TargetType.COMMUNITY: frozenset({A.SUSPEND, A.UNSUSPEND}),
    TargetType.OPPORTUNITY: frozenset({A.HIDE, A.REMOVE, A.RESTORE}),
}

# Actions that answer a complaint. Lifting something, or verifying, is not an answer to one.
RESOLVING = frozenset({A.HIDE, A.REMOVE, A.WARN, A.RESTRICT_POSTING, A.SUSPEND})

# Cutting someone off entirely, and vouching for an organization, are for admins.
ADMIN_ONLY = frozenset({A.SUSPEND, A.UNSUSPEND, A.VERIFY, A.UNVERIFY})

# Actions that last until a time, or until lifted.
TIMED = frozenset({A.SUSPEND, A.RESTRICT_POSTING})

# For an opportunity: the state each action leaves it in, and the states it can be taken
# from. Removing is final; only hiding can be undone.
OPPORTUNITY_OUTCOME = {
    A.HIDE: ModerationStatus.HIDDEN,
    A.REMOVE: ModerationStatus.REMOVED,
    A.RESTORE: ModerationStatus.VISIBLE,
}
OPPORTUNITY_ALLOWED_FROM = {
    A.HIDE: frozenset({ModerationStatus.VISIBLE}),
    A.REMOVE: frozenset({ModerationStatus.VISIBLE, ModerationStatus.HIDDEN}),
    A.RESTORE: frozenset({ModerationStatus.HIDDEN}),
}


def fitting(target: models.Model) -> frozenset[ActionType]:
    """The actions that make sense for the target as it now stands: nothing is suspended
    twice, and only something suspended can have its suspension lifted."""
    if isinstance(target, User):
        return frozenset(
            {
                A.WARN,
                A.UNSUSPEND if target.is_suspended else A.SUSPEND,
                A.UNRESTRICT_POSTING if target.is_posting_restricted else A.RESTRICT_POSTING,
            }
        )
    if isinstance(target, Organization):
        verified = target.verification_status == VerificationStatus.VERIFIED
        suspended = target.status == OrganizationStatus.SUSPENDED
        return frozenset(
            {A.UNVERIFY if verified else A.VERIFY, A.UNSUSPEND if suspended else A.SUSPEND}
        )
    if isinstance(target, Community):
        suspended = target.status == CommunityStatus.SUSPENDED
        return frozenset({A.UNSUSPEND if suspended else A.SUSPEND})
    if isinstance(target, Opportunity):
        return frozenset(
            action
            for action, sources in OPPORTUNITY_ALLOWED_FROM.items()
            if target.moderation_status in sources
        )
    return frozenset()


def may_act_on(actor: User, target: models.Model) -> bool:
    """Nobody moderates themselves, and only an admin acts on another member of staff."""
    if not isinstance(target, User):
        return True
    if target.pk == actor.pk:
        return False
    return is_admin(actor) or not is_platform_staff(target)


def open_to(actor: User, target: models.Model) -> frozenset[ActionType]:
    """What this moderator could do to the target right now."""
    if not can_moderate(actor) or not may_act_on(actor, target):
        return frozenset()
    actions = fitting(target)
    return actions if is_admin(actor) else actions - ADMIN_ONLY
