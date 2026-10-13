"""Every write to opportunities, and every move through their lifecycle.

An opportunity is two rows: the shared ``Opportunity`` and a type-specific detail row. They
are created together here, in one transaction, and the lifecycle only ever moves through the
state machine in ``policies.LIFECYCLE``.
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from audit.services import record
from common.choices import WorkMode
from common.errors import BusinessRuleViolation, Conflict, FieldErrors
from events import services as event_details
from events.policies import WORK_MODE_FOR
from jobs import services as job_details
from notifications.models import NotificationType
from notifications.services import notify
from opportunities import policies, search, selectors
from opportunities.models import (
    CloseReason,
    Opportunity,
    OpportunitySkill,
    OpportunityStatus,
    OpportunityType,
    OpportunityVisibility,
    SavedOpportunity,
)
from opportunities.policies import LIFECYCLE, Manager
from organizations.models import Organization, OrganizationStatus
from taxonomy.models import Skill
from users.models import User

MAX_SKILLS = 15
EXPIRY_BATCH = 500
S = OpportunityStatus

_LOCKED = "This cannot be changed after publishing."


def lock_opportunity(opportunity_id: UUID) -> Opportunity:
    opportunity = (
        Opportunity.objects.select_for_update(of=("self",))
        .select_related("organization", "job", "event")
        .filter(pk=opportunity_id)
        .first()
    )
    if opportunity is None:
        raise Http404
    return opportunity


def require_manager(user: User, opportunity: Opportunity) -> Manager:
    membership = selectors.get_membership(user, opportunity.organization_id)
    if not policies.can_manage(user, opportunity, membership):
        raise PermissionDenied()
    return Manager(user)


def _is_event(opportunity: Opportunity) -> bool:
    return opportunity.type == OpportunityType.EVENT


def _detail_of(opportunity: Opportunity) -> Any:
    """The type-specific row of an opportunity."""
    return opportunity.event if _is_event(opportunity) else opportunity.job


def _follow_format(fields: dict[str, Any], event: dict[str, Any]) -> None:
    """An event's work mode is not chosen: it follows from the event's format."""
    fields.pop("work_mode", None)
    if "format" in event:
        fields["work_mode"] = WORK_MODE_FOR.get(event["format"], "")


def _require_active_organization(organization: Organization | None) -> None:
    if organization is not None and organization.status != OrganizationStatus.ACTIVE:
        raise BusinessRuleViolation(
            "This organization is suspended.", code="organization_suspended"
        )


def _check_visibility(visibility: str, organization_id: UUID | None) -> None:
    if visibility == OpportunityVisibility.ORGANIZATION and organization_id is None:
        message = "Only an organization's opportunity can be limited to its members."
        raise BusinessRuleViolation(
            message, code="visibility_needs_organization", errors={"visibility": [message]}
        )


def _set_skills(opportunity: Opportunity, skill_ids: Iterable[UUID]) -> bool:
    """Make the opportunity's skills exactly ``skill_ids``. Returns whether anything changed."""
    wanted = set(skill_ids)
    if len(wanted) > MAX_SKILLS:
        message = f"Choose at most {MAX_SKILLS} skills."
        raise BusinessRuleViolation(
            message, code="too_many_skills", errors={"skill_ids": [message]}
        )
    known = set(Skill.objects.filter(pk__in=wanted).values_list("pk", flat=True))
    if known != wanted:
        raise BusinessRuleViolation(
            "Some skills do not exist.",
            code="unknown_skill",
            errors={"skill_ids": sorted(str(pk) for pk in wanted - known)},
        )
    links = OpportunitySkill.objects.filter(opportunity=opportunity)
    current = set(links.values_list("skill_id", flat=True))
    if current == wanted:
        return False
    links.filter(skill_id__in=current - wanted).delete()
    OpportunitySkill.objects.bulk_create(
        OpportunitySkill(opportunity=opportunity, skill_id=pk) for pk in wanted - current
    )
    return True


# --- Create and edit --------------------------------------------------------------------


def create_opportunity(
    *,
    creator: User,
    type: OpportunityType,
    organization_id: UUID | None = None,
    skill_ids: Iterable[UUID] = (),
    job: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    **fields: Any,
) -> Opportunity:
    """Create a draft, personal or on behalf of an organization the creator posts for.

    ``job`` or ``event`` holds the fields of that type; the one matching ``type`` is used.
    """
    if not creator.is_email_verified:
        raise PermissionDenied("Verify your email address to do this.", code="email_not_verified")
    is_event = type == OpportunityType.EVENT
    if is_event:
        event = dict(event or {})
        _follow_format(fields, event)

    organization = None
    if organization_id is not None:
        # Not being allowed to post and the organization not existing look the same.
        if not policies.can_post_for(selectors.get_membership(creator, organization_id)):
            raise PermissionDenied()
        organization = Organization.objects.get(pk=organization_id)
        _require_active_organization(organization)
    _check_visibility(fields.get("visibility", ""), organization_id)

    with transaction.atomic():
        opportunity = Opportunity.objects.create(
            creator=creator, organization=organization, type=type, **fields
        )
        if is_event:
            event_details.create_detail(opportunity, event or {})
        else:
            job_details.create_detail(opportunity, job or {})
        _set_skills(opportunity, skill_ids)
        search.reindex(opportunity)
        record(
            action="opportunity.created",
            target=opportunity,
            actor=creator,
            organization_id=organization_id,
            metadata={"type": type},
        )
        return opportunity


def _differing(instance: Any, values: dict[str, Any]) -> dict[str, Any]:
    """The values that would actually change something. A form that sends the whole object
    back must not trip over fields it did not touch."""
    return {field: value for field, value in values.items() if getattr(instance, field) != value}


def update_opportunity(
    *,
    actor: User,
    opportunity_id: UUID,
    changes: dict[str, Any],
    job_changes: dict[str, Any] | None = None,
    event_changes: dict[str, Any] | None = None,
    skill_ids: Iterable[UUID] | None = None,
) -> Opportunity:
    """Edit an opportunity. A draft is fully editable; once published, only what cannot
    mislead the people already looking at it."""
    changes = dict(changes)
    with transaction.atomic():
        opportunity = lock_opportunity(opportunity_id)
        require_manager(actor, opportunity)
        allowed = policies.editable_fields(opportunity)
        if allowed is not None and not allowed:
            raise Conflict(
                "A closed opportunity can no longer be edited.", code="opportunity_not_editable"
            )
        # From here on both types are handled alike: ``details`` is the module that knows
        # this type's rules, and ``prefix`` is how its fields are named in errors.
        details: Any
        if _is_event(opportunity):
            details, prefix = event_details, "event"
            detail_changes = dict(event_changes or {})
            _follow_format(changes, detail_changes)
        else:
            details, prefix = job_details, "job"
            detail_changes = dict(job_changes or {})
        detail = _detail_of(opportunity)
        changes = _differing(opportunity, changes)
        detail_changes = _differing(detail, detail_changes)
        current_skills = set(opportunity.skills.values_list("pk", flat=True))
        skills_differ = skill_ids is not None and set(skill_ids) != current_skills

        if allowed is not None:
            locked = [
                *(field for field in changes if field not in allowed),
                *(
                    f"{prefix}.{field}"
                    for field in detail_changes
                    if field not in details.EDITABLE_WHEN_PUBLISHED
                ),
                *(["skill_ids"] if skills_differ else []),
            ]
            if locked:
                raise BusinessRuleViolation(
                    "Some of these details cannot be changed after publishing.",
                    code="locked_after_publish",
                    errors={field: [_LOCKED] for field in locked},
                )
            deadline = changes.get("deadline")
            if deadline is not None and deadline <= timezone.now():
                message = "The deadline must be in the future."
                raise BusinessRuleViolation(
                    message, code="deadline_passed", errors={"deadline": [message]}
                )
        _check_visibility(
            changes.get("visibility", opportunity.visibility), opportunity.organization_id
        )

        for field, value in changes.items():
            setattr(opportunity, field, value)
        if changes:
            opportunity.save(update_fields=[*changes, "updated_at"])
        details.update_detail(detail, detail_changes)
        if skills_differ and skill_ids is not None:
            _set_skills(opportunity, skill_ids)
        if changes or detail_changes or skills_differ:
            search.reindex(opportunity)
            record(
                action="opportunity.updated",
                target=opportunity,
                actor=actor,
                organization_id=opportunity.organization_id,
                metadata={
                    "fields": sorted(
                        [
                            *changes,
                            *(f"{prefix}.{field}" for field in detail_changes),
                            *(["skill_ids"] if skills_differ else []),
                        ]
                    ),
                    "status": opportunity.status,
                },
            )
        return opportunity


def delete_draft(*, actor: User, opportunity_id: UUID) -> None:
    """Drafts can be deleted outright; anything that was ever published is archived instead."""
    with transaction.atomic():
        opportunity = lock_opportunity(opportunity_id)
        require_manager(actor, opportunity)
        if opportunity.status != S.DRAFT:
            raise Conflict(
                "Only a draft can be deleted. Close and archive this opportunity instead.",
                code="not_a_draft",
            )
        record(
            action="opportunity.deleted",
            target=opportunity,
            actor=actor,
            organization_id=opportunity.organization_id,
        )
        opportunity.delete()


# --- Lifecycle --------------------------------------------------------------------------


def _publication_errors(opportunity: Opportunity) -> FieldErrors:
    """Everything still missing before this can be published, keyed like the request body."""
    errors: FieldErrors = {}
    if not opportunity.description.strip():
        errors["description"] = ["Describe the opportunity."]
    if opportunity.deadline is not None and opportunity.deadline <= timezone.now():
        errors["deadline"] = ["The deadline must be in the future."]
    if _is_event(opportunity):
        # Where and when are the event's own business; skills are welcome but not required.
        return {**errors, **event_details.publication_errors(opportunity.event, opportunity)}

    if not opportunity.work_mode:
        errors["work_mode"] = ["Choose remote, hybrid or on-site."]
    elif opportunity.work_mode != WorkMode.REMOTE:
        if not opportunity.country_code:
            errors["country_code"] = ["Give the country for a hybrid or on-site role."]
        if not opportunity.city:
            errors["city"] = ["Give the city for a hybrid or on-site role."]
    if not opportunity.skills.exists():
        errors["skill_ids"] = ["Add at least one skill, so the right people can find this."]
    errors.update(job_details.publication_errors(opportunity.job))
    return errors


def publish(*, actor: User, opportunity_id: UUID) -> Opportunity:
    with transaction.atomic():
        opportunity = lock_opportunity(opportunity_id)
        manager = require_manager(actor, opportunity)
        # The state check comes first: a closed opportunity is a conflict, not a list of
        # missing fields; and publishing twice changes nothing the second time.
        if not LIFECYCLE.apply(opportunity, S.PUBLISHED, actor=manager):
            return opportunity
        _require_active_organization(opportunity.organization)
        errors = _publication_errors(opportunity)
        if errors:
            raise BusinessRuleViolation(
                "Complete these details before publishing.", code="incomplete", errors=errors
            )
        opportunity.published_at = timezone.now()
        opportunity.save(update_fields=["status", "published_at", "updated_at"])
        if _is_event(opportunity):
            event_details.publish(opportunity.event, opportunity.published_at)
        search.reindex(opportunity)
        record(
            action="opportunity.published",
            target=opportunity,
            actor=actor,
            organization_id=opportunity.organization_id,
        )
        return opportunity


def close(*, actor: User, opportunity_id: UUID, reason: CloseReason) -> Opportunity:
    """Stop taking applications for a job, or call off an event.

    An event closed by a person has been cancelled, whatever reason was sent: one that
    simply takes place is completed by the system instead.
    """
    if reason == CloseReason.COMPLETED:
        message = "Choose another reason: this one is set when an event has taken place."
        raise BusinessRuleViolation(message, code="invalid_reason", errors={"reason": [message]})
    with transaction.atomic():
        opportunity = lock_opportunity(opportunity_id)
        manager = require_manager(actor, opportunity)
        if LIFECYCLE.apply(opportunity, S.CLOSED, actor=manager):
            if _is_event(opportunity):
                event_details.cancel(opportunity.event, manager)
                reason = CloseReason.CANCELLED
            opportunity.closed_at = timezone.now()
            opportunity.close_reason = reason
            opportunity.save(update_fields=["status", "closed_at", "close_reason", "updated_at"])
            record(
                action="opportunity.closed",
                target=opportunity,
                actor=actor,
                organization_id=opportunity.organization_id,
                metadata={"reason": reason},
            )
        return opportunity


def archive(*, actor: User, opportunity_id: UUID) -> Opportunity:
    with transaction.atomic():
        opportunity = lock_opportunity(opportunity_id)
        manager = require_manager(actor, opportunity)
        if LIFECYCLE.apply(opportunity, S.ARCHIVED, actor=manager):
            opportunity.save(update_fields=["status", "updated_at"])
            record(
                action="opportunity.archived",
                target=opportunity,
                actor=actor,
                organization_id=opportunity.organization_id,
            )
        return opportunity


def save_for_later(*, user: User, opportunity_id: UUID) -> None:
    """Bookmark an opportunity the user can see. Saving twice changes nothing."""
    opportunity = selectors.get_opportunity(user, opportunity_id)
    # get_or_create relies on the unique constraint to settle a double click.
    SavedOpportunity.objects.get_or_create(user=user, opportunity=opportunity)


def unsave(*, user: User, opportunity_id: UUID) -> None:
    """Remove a bookmark. Works even if the opportunity is no longer visible to the user."""
    SavedOpportunity.objects.filter(user=user, opportunity_id=opportunity_id).delete()


def expire_due() -> int:
    """Expire published opportunities whose deadline has passed. Returns how many.

    Safe to run at any time and any number of times. Each row is moved by a conditional
    update, so one that a manager closes at the same moment stays closed, and a row is never
    expired or audited twice. Events are excluded: their deadline ends registration, not the
    event.
    """
    now = timezone.now()
    due = Opportunity.objects.filter(status=S.PUBLISHED, deadline__lt=now).exclude(
        type=OpportunityType.EVENT
    )
    expired = 0
    for opportunity in due.select_related("creator").order_by("deadline")[:EXPIRY_BATCH]:
        with transaction.atomic():
            # The same move as PUBLISHED -> EXPIRED in the lifecycle, made by the system.
            moved = Opportunity.objects.filter(
                pk=opportunity.pk, status=S.PUBLISHED, deadline__lt=now
            ).update(status=S.EXPIRED, closed_at=now, updated_at=now)
            if moved:
                record(
                    action="opportunity.expired",
                    target=opportunity,
                    organization_id=opportunity.organization_id,
                )
                # Keyed, so a rerun of the sweep can never tell the same person twice.
                notify(
                    recipient=opportunity.creator,
                    type=NotificationType.OPPORTUNITY_EXPIRED,
                    target=opportunity,
                    payload={
                        "opportunity_id": str(opportunity.pk),
                        "opportunity_title": opportunity.title,
                    },
                    dedupe_key=f"opportunity-expired:{opportunity.pk}",
                )
                expired += 1
    return expired
