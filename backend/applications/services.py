"""Every write to applications, and every move through the pipeline."""

import uuid
from functools import partial
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied

from applications import policies, selectors
from applications.models import Application, ApplicationStatus, ApplicationStatusHistory
from applications.policies import BARRIER_MESSAGES, PIPELINE, Barrier
from audit.services import record
from common.errors import BusinessRuleViolation, Conflict, InvalidTransition
from common.storage import download_url, private_storage
from common.tasks import enqueue
from notifications.models import NotificationType
from notifications.services import notify, notify_each
from opportunities import selectors as opportunities
from opportunities.models import Opportunity, OpportunityType
from realtime.tasks import publish_event
from users.models import User

S = ApplicationStatus
# Where a manager may send an application. Withdrawing is the applicant's, and has its own
# function.
MANAGER_TARGETS = frozenset({*policies.STAGES[1:], S.REJECTED})

_PDF_MAGIC = b"%PDF-"


def _read_resume(upload: UploadedFile[Any] | None) -> bytes:
    """The uploaded resume's bytes, if it is an acceptable PDF.

    Judged by its content. The filename and the content type the browser sent are chosen by
    the client, so neither is looked at.
    """

    def invalid(message: str, code: str) -> BusinessRuleViolation:
        return BusinessRuleViolation(message, code=code, errors={"resume": [message]})

    if upload is None:
        raise invalid("Attach your resume as a PDF.", "file_required")
    if upload.size is None or upload.size > settings.RESUME_MAX_BYTES:
        limit_mb = settings.RESUME_MAX_BYTES // (1024 * 1024)
        raise invalid(f"The resume must be {limit_mb} MB or smaller.", "file_too_large")
    content: bytes = upload.read()
    if not content.startswith(_PDF_MAGIC):
        raise invalid("The resume must be a PDF file.", "invalid_file")
    return content


def _about(application: Application, opportunity: Opportunity, applicant: User) -> dict[str, str]:
    """What a notification about this application needs in order to be worded later."""
    return {
        "application_id": str(application.pk),
        "opportunity_id": str(opportunity.pk),
        "opportunity_title": opportunity.title,
        "person_name": applicant.profile.display_name,
    }


def apply(
    *, applicant: User, opportunity_id: UUID, resume: UploadedFile[Any] | None, cover_note: str
) -> tuple[Application, bool]:
    """Apply to a job. Returns the application and whether this call created it.

    Applying twice is not an error: the application that already exists is returned, in
    whatever state it is, and the second upload is discarded. That covers a double click as
    well as someone coming back to a job they applied to (or withdrew from) earlier.
    """
    opportunity = opportunities.get_opportunity(applicant, opportunity_id)
    if opportunity.type != OpportunityType.JOB:
        raise Http404
    existing = Application.objects.filter(opportunity=opportunity, applicant=applicant).first()
    if existing is not None:
        return existing, False

    barrier = selectors.barrier_to_applying(applicant, opportunity)
    if barrier is not None:
        error = Conflict if barrier is Barrier.NOT_ACCEPTING else BusinessRuleViolation
        raise error(BARRIER_MESSAGES[barrier], code=barrier.value)
    content = _read_resume(resume)

    # Stored before the transaction (no file I/O while holding database locks), and removed
    # again if the row does not get created.
    storage = private_storage()
    key = storage.save(f"resumes/{uuid.uuid4().hex}.pdf", ContentFile(content))
    try:
        with transaction.atomic():
            now = timezone.now()
            application = Application.objects.create(
                opportunity=opportunity,
                applicant=applicant,
                resume=key,
                cover_note=cover_note,
                headline=applicant.profile.headline,
                status_changed_at=now,
            )
            ApplicationStatusHistory.objects.create(
                application=application, to_status=S.APPLIED, actor=applicant
            )
            record(
                action="application.submitted",
                target=application,
                actor=applicant,
                organization_id=opportunity.organization_id,
                metadata={"opportunity_id": str(opportunity.pk)},
            )
            notify_each(
                selectors.managers_of(opportunity),
                type=NotificationType.APPLICATION_RECEIVED,
                target=application,
                actor=applicant,
                payload=_about(application, opportunity, applicant),
            )
    except IntegrityError:
        # The same person, twice at once: the unique constraint let one through.
        storage.delete(key)
        return Application.objects.get(opportunity=opportunity, applicant=applicant), False
    except BaseException:
        storage.delete(key)
        raise
    return application, True


def _lock(user: User, application_id: UUID) -> Application:
    application = (
        selectors.visible_to(user)
        .select_for_update(of=("self",))
        .select_related("opportunity", "applicant__profile")
        .filter(pk=application_id)
        .first()
    )
    if application is None:
        raise Http404
    return application


def _save_move(
    application: Application, previous: str, *, by: User, action: str, note: str = ""
) -> None:
    """The bookkeeping every move shares. The status itself was set by the state machine."""
    application.status_changed_at = timezone.now()
    application.save(update_fields=["status", "status_changed_at", "updated_at"])
    ApplicationStatusHistory.objects.create(
        application=application,
        from_status=previous,
        to_status=application.status,
        actor=by,
        note=note,
    )
    # The note stays out of the audit log: it is an opinion about a person, and the log is
    # read by more people than the application is.
    record(
        action=action,
        target=application,
        actor=by,
        organization_id=application.opportunity.organization_id,
        metadata={"from": previous, "to": application.status},
    )


def transition(
    *,
    user: User,
    application_id: UUID,
    to: ApplicationStatus,
    expected: ApplicationStatus | None = None,
    note: str = "",
) -> Application:
    """Move an application to a later stage, or reject it. For whoever manages the job.

    ``expected`` is the status the caller was looking at. If someone else moved the
    application in the meantime the move is refused (409 ``stale_state``), so two recruiters
    cannot silently overrule each other. Asking for the status it already has is a repeat of
    a move that worked, and changes nothing.
    """
    if to not in MANAGER_TARGETS:
        raise InvalidTransition("An application cannot be moved there this way.")
    with transaction.atomic():
        application = _lock(user, application_id)
        actor = selectors.actor_for(user, application)
        if not policies.decides(actor):
            raise PermissionDenied()
        previous = application.status
        if previous == to:
            return application
        if PIPELINE.apply(application, to, actor=actor, expected=expected):
            _save_move(
                application, previous, by=user, action="application.status_changed", note=note
            )
            opportunity, applicant = application.opportunity, application.applicant
            rejected = to == S.REJECTED
            notify(
                recipient=applicant,
                type=NotificationType.APPLICATION_REJECTED
                if rejected
                else NotificationType.APPLICATION_ADVANCED,
                target=application,
                # Deliberately no actor: the applicant hears from the employer, not from
                # whichever recruiter pressed the button.
                payload={
                    **_about(application, opportunity, applicant),
                    "status": to.value,
                    "status_label": to.label,
                },
            )
            # So an open "my applications" page updates without a reload. Only a hint: the
            # page refetches through the API.
            transaction.on_commit(
                partial(
                    enqueue,
                    publish_event,
                    str(applicant.pk),
                    "application.updated",
                    {"id": str(application.pk), "status": to.value},
                )
            )
        return application


def withdraw(*, user: User, application_id: UUID) -> Application:
    """Take one's own application back. Doing it twice changes nothing."""
    with transaction.atomic():
        application = _lock(user, application_id)
        previous = application.status
        actor = selectors.actor_for(user, application)
        if PIPELINE.apply(application, S.WITHDRAWN, actor=actor):
            _save_move(application, previous, by=user, action="application.withdrawn")
            opportunity = application.opportunity
            notify_each(
                selectors.managers_of(opportunity),
                type=NotificationType.APPLICATION_WITHDRAWN,
                target=application,
                actor=user,
                payload=_about(application, opportunity, application.applicant),
            )
        return application


def resume_link(*, user: User, application_id: UUID) -> str:
    """A short-lived link to the resume, for the applicant or someone managing the job.

    Each time an employer takes one, it is written to the audit log: a resume is personal
    data, and its owner is entitled to know who looked.
    """
    application = selectors.get_application(user, application_id)
    actor = selectors.actor_for(user, application)
    if not policies.can_download_resume(actor, application):
        raise PermissionDenied()
    if not actor.is_applicant:
        record(
            action="application.resume_downloaded",
            target=application,
            actor=user,
            organization_id=application.opportunity.organization_id,
        )
    name = slugify(application.applicant.profile.display_name) or "applicant"
    return download_url(
        application.resume, filename=f"resume-{name}.pdf", content_type="application/pdf"
    )
