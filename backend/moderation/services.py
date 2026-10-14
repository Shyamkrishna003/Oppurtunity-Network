"""Every write in moderation: filing reports, deciding them, and acting on what they are about.

Everything a moderator does is recorded twice over: as a ``ModerationAction`` row, which is
what the queue and the target's history show, and in the audit log.
"""

from datetime import UTC, datetime
from uuid import UUID

from django.db import IntegrityError, models, transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from audit.services import record
from common.errors import BusinessRuleViolation, Conflict
from communities import selectors as communities
from communities.models import Community, CommunityStatus
from communities.policies import actor_for, can_review_requests, is_member
from moderation import policies, selectors
from moderation.models import (
    ActionType,
    ModerationAction,
    Report,
    ReportCategory,
    ReportStatus,
    TargetType,
    target_field,
)
from moderation.policies import REPORT, Moderator
from notifications.models import NotificationType
from notifications.services import notify, notify_each
from opportunities import distribution
from opportunities.models import DistributionStatus, Opportunity, OpportunityCommunity
from organizations.models import Organization, OrganizationStatus, VerificationStatus
from users.models import User
from users.services.auth import end_all_sessions

S = ReportStatus
A = ActionType

# How "until a moderator lifts it" is stored in a column that holds a time.
UNTIL_LIFTED = datetime(9999, 12, 31, tzinfo=UTC)

_MODELS: dict[TargetType, type[models.Model]] = {
    TargetType.USER: User,
    TargetType.ORGANIZATION: Organization,
    TargetType.COMMUNITY: Community,
    TargetType.OPPORTUNITY: Opportunity,
}


def _community_to_report_to(reporter: User, target: models.Model, community_id: UUID) -> Community:
    """The community whose moderators a report is sent to. Only its members can do that, and
    only about an opportunity it shows: what a community's moderators can do is take
    something out of their community, nothing more."""
    if not isinstance(target, Opportunity):
        raise BusinessRuleViolation(
            "Only an opportunity can be reported to a community's moderators.",
            code="community_scope_unavailable",
        )
    community = communities.get_community(reporter, community_id)
    membership = communities.get_membership(reporter, community)
    if not is_member(actor_for(reporter.pk, membership)):
        raise BusinessRuleViolation(
            "Only members can report to this community's moderators.", code="not_a_member"
        )
    if not selectors.is_shown_in(community.pk, target.pk):
        raise BusinessRuleViolation(
            "This community does not show this opportunity.", code="not_in_community"
        )
    return community


def file_report(
    *,
    reporter: User,
    target_type: TargetType,
    target_id: UUID,
    category: ReportCategory,
    description: str,
    community_id: UUID | None = None,
) -> Report:
    """Report something to the platform's moderators, or with ``community_id`` to the
    moderators of a community that shows it.

    The reporter must be able to see it, and cannot report themselves or what they manage.
    One report per person and thing can be in progress at a time.
    """
    target = selectors.find_target(reporter, target_type, target_id)
    if selectors.is_own(reporter, target):
        raise BusinessRuleViolation("You cannot report your own content.", code="own_content")
    community = (
        None if community_id is None else _community_to_report_to(reporter, target, community_id)
    )
    try:
        with transaction.atomic():
            # The community's moderators are told once per thing, not once per complaint.
            news = (
                community is not None
                and not Report.objects.filter(
                    **selectors.about(target_type, target_id),
                    scope_community=community,
                    status__in=policies.IN_PROGRESS,
                ).exists()
            )
            report = Report.objects.create(
                reporter=reporter,
                target_type=target_type,
                category=category,
                description=description.strip(),
                scope_community=community,
                **{target_field(target_type): target},
            )
            # Not filed under the community: its owners read that trail, and who reported
            # is not theirs to know.
            record(
                action="report.filed",
                target=report,
                actor=reporter,
                metadata={
                    "target_type": target_type,
                    "target_id": str(target_id),
                    "category": category,
                },
            )
            if community is not None and news and isinstance(target, Opportunity):
                notify_each(
                    communities.reviewers(community).exclude(pk=reporter.pk),
                    type=NotificationType.COMMUNITY_REPORT_FILED,
                    target=report,
                    payload={
                        "community_id": str(community.pk),
                        "community_name": community.name,
                        "opportunity_id": str(target.pk),
                        "opportunity_title": target.title,
                    },
                )
            return report
    except IntegrityError as exc:
        raise Conflict(
            "You have already reported this, and the report is still being looked at.",
            code="already_reported",
        ) from exc


def _moderator(user: User) -> Moderator:
    if not policies.can_moderate(user):
        raise PermissionDenied()
    return Moderator(user)


def require_community_moderator(actor: User, community_id: UUID) -> Community:
    """The community, for one of its moderators, admins or owners. 404 if the caller cannot
    see it at all, 403 if they are not one of those."""
    community = communities.get_community(actor, community_id)
    acting = actor_for(actor.pk, communities.get_membership(actor, community))
    if not can_review_requests(acting):
        raise PermissionDenied()
    return community


def _require_authority(actor: User, community_id: UUID | None) -> None:
    """The platform's staff decide the platform's reports; a community's moderators decide
    the ones sent to that community. Neither decides the other's."""
    if community_id is None:
        _moderator(actor)
    else:
        require_community_moderator(actor, community_id)


def _deciding(actor: User, report: Report) -> Moderator:
    """The actor as someone about to decide this report, their authority already checked."""
    manages = report.scope_community_id is not None and selectors.is_own(actor, report.target)
    return Moderator(actor, manages_target=manages)


def _lock_report(report_id: UUID, community_id: UUID | None = None) -> Report:
    """Lock a report in the platform's queue, or with ``community_id`` in that community's."""
    report = (
        Report.objects.select_for_update()
        .filter(pk=report_id, scope_community_id=community_id)
        .first()
    )
    if report is None:
        raise Http404
    return report


def claim(*, actor: User, report_id: UUID, community_id: UUID | None = None) -> Report:
    """Take a report on. Claiming one that is already under review changes nothing."""
    _require_authority(actor, community_id)
    with transaction.atomic():
        report = _lock_report(report_id, community_id)
        if REPORT.apply(report, S.UNDER_REVIEW, actor=_deciding(actor, report)):
            report.assigned_to = actor
            report.save(update_fields=["status", "assigned_to", "updated_at"])
            record(action="report.claimed", target=report, actor=actor, community_id=community_id)
    return selectors.get_report(report_id, community_id=community_id)


def _close(report: Report, status: ReportStatus, *, by: User, note: str) -> None:
    """Record a report's outcome and tell whoever made it. The caller has applied the move."""
    report.status = status
    report.resolved_by = by
    report.resolved_at = timezone.now()
    report.resolution_note = note
    report.save(
        update_fields=["status", "resolved_by", "resolved_at", "resolution_note", "updated_at"]
    )
    record(
        action="report.resolved",
        target=report,
        actor=by,
        community_id=report.scope_community_id,
        metadata={"outcome": status},
    )
    # The same words whatever was decided: the outcome for someone else is not theirs to know.
    notify(
        recipient=report.reporter,
        type=NotificationType.REPORT_REVIEWED,
        target=report,
        payload={"report_id": str(report.pk)},
    )


def dismiss(*, actor: User, report_id: UUID, note: str, community_id: UUID | None = None) -> Report:
    """Decide that a report needs no action."""
    _require_authority(actor, community_id)
    with transaction.atomic():
        report = _lock_report(report_id, community_id)
        if REPORT.apply(report, S.DISMISSED, actor=_deciding(actor, report)):
            _close(report, S.DISMISSED, by=actor, note=note.strip())
    return selectors.get_report(report_id, community_id=community_id)


# --- What a community's moderators can do -------------------------------------------------


def remove_from_community(
    *, actor: User, community_id: UUID, report_id: UUID, reason: str
) -> Report:
    """Answer a community's report by taking the opportunity out of that community.

    It stays wherever else it is shown: one community's decision is never another's. Every
    report about it still waiting in this community is settled, since they all asked for
    the same thing.
    """
    _require_authority(actor, community_id)
    reason = reason.strip()
    if not reason:
        message = "Say why, for the record."
        raise BusinessRuleViolation(message, code="reason_required", errors={"reason": [message]})
    with transaction.atomic():
        report = _lock_report(report_id, community_id)
        if not REPORT.apply(report, S.ACTION_TAKEN, actor=_deciding(actor, report)):
            raise Conflict("This report has already been decided.", code="already_resolved")
        shown = OpportunityCommunity.objects.filter(
            community_id=community_id,
            opportunity_id=report.target_id,
            status=DistributionStatus.APPROVED,
        ).first()
        if shown is None:
            raise Conflict(
                "This community no longer shows this opportunity.", code="action_not_possible"
            )
        # The community's own removal: its rules, its record, and its word to whoever shared.
        distribution.review(
            actor=actor,
            community_id=community_id,
            share_id=shown.pk,
            decision=DistributionStatus.REMOVED,
        )
        others = (
            Report.objects.select_for_update()
            .filter(
                **selectors.about(report.target_type, report.target_id),
                scope_community_id=community_id,
                status__in=policies.IN_PROGRESS,
            )
            .exclude(pk=report.pk)
        )
        for settled in [report, *others]:
            _close(settled, S.ACTION_TAKEN, by=actor, note=reason)
    return selectors.get_report(report_id, community_id=community_id)


def escalate(*, actor: User, community_id: UUID, report_id: UUID) -> None:
    """Pass a community's report up to the platform's moderators, for something that taking
    it out of one community would not put right. It leaves the community's queue and waits
    in the platform's as if it had been sent there."""
    _require_authority(actor, community_id)
    with transaction.atomic():
        report = _lock_report(report_id, community_id)
        if report.status not in policies.IN_PROGRESS:
            raise Conflict("This report has already been decided.", code="already_resolved")
        deciding = _deciding(actor, report)
        if report.status == S.UNDER_REVIEW:
            REPORT.apply(report, S.OPEN, actor=deciding)
        elif not policies.uninvolved(deciding, report):
            raise PermissionDenied()
        report.scope_community = None
        report.assigned_to = None
        report.save(update_fields=["status", "scope_community", "assigned_to", "updated_at"])
        record(action="report.escalated", target=report, actor=actor, community_id=community_id)


# --- Acting on a target -----------------------------------------------------------------


def _lock_target(target_type: TargetType, target_id: UUID) -> models.Model:
    manager = _MODELS[target_type].objects  # type: ignore[attr-defined]
    target: models.Model | None = manager.select_for_update().filter(pk=target_id).first()
    if target is None:
        raise Http404
    return target


def _apply(target: models.Model, action: ActionType, until: datetime | None) -> None:
    """Make the change itself. The caller holds a lock on the target and has checked that
    the action fits it as it stands."""
    lasting = until or UNTIL_LIFTED
    if isinstance(target, Opportunity):
        target.moderation_status = policies.OPPORTUNITY_OUTCOME[action]
        target.save(update_fields=["moderation_status", "updated_at"])
    elif isinstance(target, User):
        if action in (A.SUSPEND, A.UNSUSPEND):
            target.suspended_until = lasting if action == A.SUSPEND else None
            target.save(update_fields=["suspended_until", "updated_at"])
            if action == A.SUSPEND:
                # Signed out everywhere, now: tokens revoked and open pages disconnected.
                end_all_sessions(target)
        elif action in (A.RESTRICT_POSTING, A.UNRESTRICT_POSTING):
            target.posting_restricted_until = lasting if action == A.RESTRICT_POSTING else None
            target.save(update_fields=["posting_restricted_until", "updated_at"])
        # A warning changes nothing but what the person is told.
    elif isinstance(target, Organization):
        if action in (A.VERIFY, A.UNVERIFY):
            target.verification_status = (
                VerificationStatus.VERIFIED if action == A.VERIFY else VerificationStatus.UNVERIFIED
            )
            target.save(update_fields=["verification_status", "updated_at"])
        else:
            target.status = (
                OrganizationStatus.SUSPENDED if action == A.SUSPEND else OrganizationStatus.ACTIVE
            )
            target.save(update_fields=["status", "updated_at"])
    elif isinstance(target, Community):
        target.status = CommunityStatus.SUSPENDED if action == A.SUSPEND else CommunityStatus.ACTIVE
        target.save(update_fields=["status", "updated_at"])


def _tell_those_affected(
    target: models.Model, action: ActionType, reason: str, until: datetime | None
) -> None:
    """Tell the person, or the people who run the thing, what was done and why. Never who
    reported it."""
    described = selectors.describe(target)
    payload = {
        "action": action,
        "reason": reason,
        "name": described.label,
        "until": until.date().isoformat() if until else "",
    }
    if isinstance(target, Opportunity):
        kind = NotificationType.OPPORTUNITY_MODERATED
        payload |= {"opportunity_id": str(target.pk), "opportunity_title": target.title}
    elif isinstance(target, User):
        kind = NotificationType.ACCOUNT_MODERATED
    elif isinstance(target, Organization):
        kind = NotificationType.ORGANIZATION_MODERATED
        payload |= {"organization_id": str(target.pk)}
    else:
        kind = NotificationType.COMMUNITY_MODERATED
        payload |= {"community_id": str(target.pk)}
    notify_each(selectors.responsible_for(target), type=kind, target=target, payload=payload)


def act(
    *,
    actor: User,
    target_type: TargetType,
    target_id: UUID,
    action: ActionType,
    reason: str,
    until: datetime | None = None,
    report_id: UUID | None = None,
) -> ModerationAction:
    """Do something to a person, organization, community or opportunity, as a moderator.

    With ``report_id``, this is the answer to that report. Either way, an action that
    answers complaints settles every report about the target that was still waiting, since
    they were all asking for the same thing.

    ``until`` is for a suspension or a posting restriction: when it lapses by itself.
    Without it, it lasts until a moderator lifts it.
    """
    moderator = _moderator(actor)
    reason = reason.strip()
    if not reason:
        message = "Say why, for the record and for the people affected."
        raise BusinessRuleViolation(message, code="reason_required", errors={"reason": [message]})
    if action not in policies.ACTIONS_FOR[target_type]:
        raise BusinessRuleViolation(
            "This action is not available for this kind of thing.", code="action_unavailable"
        )
    if until is not None and (action not in policies.TIMED or until <= timezone.now()):
        message = (
            "Give a time in the future."
            if action in policies.TIMED
            else "This action does not take an end time."
        )
        raise BusinessRuleViolation(message, code="invalid_until", errors={"until": [message]})

    with transaction.atomic():
        report = None
        if report_id is not None:
            report = _lock_report(report_id)
            if (report.target_type, report.target_id) != (target_type, target_id):
                raise Http404
            if action not in policies.RESOLVING:
                raise BusinessRuleViolation(
                    "This action does not answer a report.", code="action_unavailable"
                )
            # Checks that the report is still open and that this moderator may decide it.
            # The status itself is written below, with every other report on the target.
            if not REPORT.apply(report, S.ACTION_TAKEN, actor=moderator):
                raise Conflict("This report has already been decided.", code="already_resolved")

        target = _lock_target(target_type, target_id)
        if not policies.may_act_on(actor, target) or (
            action in policies.ADMIN_ONLY and not policies.is_admin(actor)
        ):
            raise PermissionDenied()
        if action not in policies.fitting(target):
            raise Conflict("This cannot be done as things now stand.", code="action_not_possible")
        _apply(target, action, until)

        taken = ModerationAction.objects.create(
            actor=actor,
            action_type=action,
            target_type=target_type,
            report=report,
            reason=reason,
            expires_at=until if action in policies.TIMED else None,
            **{target_field(target_type): target},
        )
        record(
            action="moderation.action_taken",
            target=target,
            actor=actor,
            organization_id=getattr(target, "organization_id", None)
            or (target.pk if isinstance(target, Organization) else None),
            community_id=target.pk if isinstance(target, Community) else None,
            metadata={
                "action": action,
                "moderation_action_id": str(taken.pk),
                "until": until.isoformat() if until else None,
            },
        )
        _tell_those_affected(target, action, reason, until)

        if action in policies.RESOLVING:
            waiting = Report.objects.select_for_update().filter(
                **selectors.about(target_type, target_id), status__in=policies.IN_PROGRESS
            )
            # The report being answered was moved above but not saved; the rest are found
            # here. All of them are written, and their reporters told, the same way.
            settled = [] if report is None else [report]
            others = waiting if report is None else waiting.exclude(pk=report.pk)
            for other in [*settled, *others]:
                _close(other, S.ACTION_TAKEN, by=actor, note=reason)
        return taken
