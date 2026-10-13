"""Every write in moderation: filing reports, deciding them, and acting on what they are about.

Everything a moderator does is recorded twice over: as a ``ModerationAction`` row, which is
what the queue and the target's history show, and in the audit log.
"""

from uuid import UUID

from django.db import IntegrityError, models, transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from applications.selectors import managers_of
from audit.services import record
from common.errors import BusinessRuleViolation, Conflict
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
from opportunities.models import Opportunity
from users.models import User

S = ReportStatus


def file_report(
    *,
    reporter: User,
    target_type: TargetType,
    target_id: UUID,
    category: ReportCategory,
    description: str,
) -> Report:
    """Report something to the moderators.

    The reporter must be able to see it, and cannot report themselves or what they manage.
    One report per person and thing can be in progress at a time.
    """
    target = selectors.find_target(reporter, target_type, target_id)
    if selectors.is_own(reporter, target):
        raise BusinessRuleViolation("You cannot report your own content.", code="own_content")
    try:
        with transaction.atomic():
            report = Report.objects.create(
                reporter=reporter,
                target_type=target_type,
                category=category,
                description=description.strip(),
                **{target_field(target_type): target},
            )
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


def _lock_report(report_id: UUID) -> Report:
    report = Report.objects.select_for_update().filter(pk=report_id).first()
    if report is None:
        raise Http404
    return report


def claim(*, actor: User, report_id: UUID) -> Report:
    """Take a report on. Claiming one that is already under review changes nothing."""
    moderator = _moderator(actor)
    with transaction.atomic():
        report = _lock_report(report_id)
        if REPORT.apply(report, S.UNDER_REVIEW, actor=moderator):
            report.assigned_to = actor
            report.save(update_fields=["status", "assigned_to", "updated_at"])
            record(action="report.claimed", target=report, actor=actor)
    return selectors.get_report(report_id)


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
        metadata={"outcome": status},
    )
    # The same words whatever was decided: the outcome for someone else is not theirs to know.
    notify(
        recipient=report.reporter,
        type=NotificationType.REPORT_REVIEWED,
        target=report,
        payload={"report_id": str(report.pk)},
    )


def dismiss(*, actor: User, report_id: UUID, note: str) -> Report:
    """Decide that a report needs no action."""
    moderator = _moderator(actor)
    with transaction.atomic():
        report = _lock_report(report_id)
        if REPORT.apply(report, S.DISMISSED, actor=moderator):
            _close(report, S.DISMISSED, by=actor, note=note.strip())
    return selectors.get_report(report_id)


def _apply_to_opportunity(opportunity_id: UUID, action: ActionType) -> Opportunity:
    opportunity = (
        Opportunity.objects.select_for_update(of=("self",)).filter(pk=opportunity_id).first()
    )
    if opportunity is None:
        raise Http404
    if opportunity.moderation_status not in policies.OPPORTUNITY_ALLOWED_FROM[action]:
        raise Conflict(
            "This cannot be done to the opportunity as it now stands.", code="action_not_possible"
        )
    opportunity.moderation_status = policies.OPPORTUNITY_OUTCOME[action]
    opportunity.save(update_fields=["moderation_status", "updated_at"])
    return opportunity


def act(
    *,
    actor: User,
    target_type: TargetType,
    target_id: UUID,
    action: ActionType,
    reason: str,
    report_id: UUID | None = None,
) -> ModerationAction:
    """Do something to a person, organization, community or opportunity, as a moderator.

    With ``report_id``, this is the answer to that report. Either way, hiding or removing
    something settles every report about it that was still waiting, since they were all
    asking for the same thing.
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

        target: models.Model = _apply_to_opportunity(target_id, action)
        taken = ModerationAction.objects.create(
            actor=actor,
            action_type=action,
            target_type=target_type,
            report=report,
            reason=reason,
            **{target_field(target_type): target},
        )
        record(
            action="moderation.action_taken",
            target=target,
            actor=actor,
            organization_id=getattr(target, "organization_id", None),
            metadata={"action": action, "moderation_action_id": str(taken.pk)},
        )
        if isinstance(target, Opportunity):
            notify_each(
                managers_of(target),
                type=NotificationType.OPPORTUNITY_MODERATED,
                target=target,
                payload={
                    "opportunity_id": str(target.pk),
                    "opportunity_title": target.title,
                    "action": action,
                    "reason": reason,
                },
            )
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
