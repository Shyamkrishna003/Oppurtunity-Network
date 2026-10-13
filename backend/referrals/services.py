"""Every write to referrals, and every move through the workflow."""

from functools import partial
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from applications.models import Application
from audit.services import record
from common.errors import BusinessRuleViolation, Conflict
from common.tasks import enqueue
from notifications.models import NotificationType
from notifications.services import notify, retract
from opportunities.models import OpportunityStatus
from realtime.tasks import publish_event
from referrals import policies, selectors
from referrals.models import ReferralRequest, ReferralStatus, ReferralStatusHistory
from referrals.policies import BARRIER_MESSAGES, MAX_OPEN_PER_JOB, MIRROR, WORKFLOW, Barrier
from users.models import User

S = ReferralStatus
T = NotificationType
SWEEP_BATCH = 200

# Outcomes the referrer is told about. The stages in between are the requester's business.
_OUTCOMES_ANNOUNCED = frozenset({S.APPLICATION_SUBMITTED, S.JOINED})


def _about(referral: ReferralRequest) -> dict[str, str]:
    """What a notification about this referral needs in order to be worded later."""
    return {
        "referral_id": str(referral.pk),
        "opportunity_id": str(referral.opportunity_id),
        "opportunity_title": referral.opportunity.title,
        "requester_name": referral.requester.profile.display_name,
        "referrer_name": referral.referrer.profile.display_name,
    }


def _announce(referral: ReferralRequest, *user_ids: UUID) -> None:
    """Tell these people's open pages that the referral changed. Only a hint: the pages
    refetch through the API."""
    data = {"id": str(referral.pk), "status": str(referral.status)}
    for user_id in user_ids:
        transaction.on_commit(
            partial(enqueue, publish_event, str(user_id), "referral.updated", data)
        )


def _save_move(
    referral: ReferralRequest,
    previous: str,
    *,
    by: User | None,
    action: str,
    fields: tuple[str, ...] = (),
) -> None:
    """The bookkeeping every move shares. The status itself was set by the state machine."""
    referral.status_changed_at = timezone.now()
    referral.save(update_fields=["status", "status_changed_at", "updated_at", *fields])
    ReferralStatusHistory.objects.create(
        referral=referral, from_status=previous, to_status=referral.status, actor=by
    )
    # Neither the message nor the endorsement goes into the audit log: both are personal,
    # and the log is read by more people than the referral is.
    record(
        action=action,
        target=referral,
        actor=by,
        organization_id=referral.opportunity.organization_id,
        metadata={"from": previous, "to": referral.status},
    )


# --- Asking -----------------------------------------------------------------------------


def _lock_requests_for(requester_id: UUID, opportunity_id: UUID) -> None:
    """Serialize one person's requests for one job until the transaction ends, so that two
    sent at once cannot both pass the limit check."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [f"referral-request:{requester_id}:{opportunity_id}"],
        )


def request(
    *, user: User, opportunity_id: UUID, referrer_id: UUID, message: str
) -> ReferralRequest:
    """Ask one of the user's own connections to refer them for a job.

    The answer to "may I ask this person" is the same (422 ``not_eligible``) whether they are
    not a connection, not a member of the organization, do not show that they are, do not
    take referral requests, or do not exist: asking must not be a way to find out who works
    where.
    """
    opportunity = selectors.get_job(user, opportunity_id)
    barrier = selectors.barrier_to_requesting(user, opportunity)
    if barrier is not None:
        error = Conflict if barrier is Barrier.NOT_ACCEPTING else BusinessRuleViolation
        raise error(BARRIER_MESSAGES[barrier], code=barrier.value)
    referrer = selectors.get_eligible_referrer(user, opportunity, referrer_id)
    if referrer is None:
        raise BusinessRuleViolation(
            "This person cannot be asked to refer you for this job.", code="not_eligible"
        )

    with transaction.atomic():
        _lock_requests_for(user.pk, opportunity.pk)
        mine = ReferralRequest.objects.filter(opportunity=opportunity, requester=user)
        if mine.filter(referrer=referrer).exists():
            raise Conflict(
                "You have already asked this person about this job.", code="already_requested"
            )
        if selectors.open_count(user, opportunity) >= MAX_OPEN_PER_JOB:
            raise Conflict(
                f"You can have {MAX_OPEN_PER_JOB} referral requests open for one job at a time.",
                code="too_many_requests",
            )
        now = timezone.now()
        referral = ReferralRequest.objects.create(
            opportunity=opportunity,
            requester=user,
            referrer=referrer,
            message=message,
            expires_at=now + settings.REFERRAL_REQUEST_LIFETIME,
            status_changed_at=now,
        )
        ReferralStatusHistory.objects.create(referral=referral, to_status=S.REQUESTED, actor=user)
        record(
            action="referral.requested",
            target=referral,
            actor=user,
            organization_id=opportunity.organization_id,
            metadata={"opportunity_id": str(opportunity.pk)},
        )
        notify(
            recipient=referrer,
            type=T.REFERRAL_REQUESTED,
            target=referral,
            actor=user,
            payload=_about(referral),
        )
        _announce(referral, referrer.pk)
    return referral


# --- The two people's moves -------------------------------------------------------------


def _lock(user: User, referral_id: UUID) -> ReferralRequest:
    referral = (
        selectors.visible_to(user)
        .select_for_update(of=("self",))
        .select_related("opportunity__job", "requester__profile", "referrer__profile")
        .filter(pk=referral_id)
        .first()
    )
    if referral is None:
        raise Http404
    return referral


def _answer(*, user: User, referral_id: UUID, to: ReferralStatus, tell: NotificationType) -> None:
    """A move by the referrer that the requester is told about."""
    with transaction.atomic():
        referral = _lock(user, referral_id)
        previous = referral.status
        if WORKFLOW.apply(referral, to, actor=selectors.actor_for(user, referral)):
            referral.responded_at = referral.responded_at or timezone.now()
            _save_move(
                referral,
                previous,
                by=user,
                action=f"referral.{to.lower()}",
                fields=("responded_at",),
            )
            notify(
                recipient=referral.requester,
                type=tell,
                target=referral,
                actor=user,
                payload=_about(referral),
            )
            _announce(referral, referral.requester_id)


def accept(*, user: User, referral_id: UUID) -> None:
    """Agree to refer. Nothing reaches the employer yet: that is ``refer``."""
    _answer(user=user, referral_id=referral_id, to=S.ACCEPTED, tell=T.REFERRAL_ACCEPTED)


def decline(*, user: User, referral_id: UUID) -> None:
    """Say no. No reason is asked for or passed on."""
    _answer(user=user, referral_id=referral_id, to=S.DECLINED, tell=T.REFERRAL_DECLINED)


def back_out(*, user: User, referral_id: UUID) -> None:
    """Change one's mind after agreeing, before the referral is made."""
    _answer(user=user, referral_id=referral_id, to=S.CLOSED, tell=T.REFERRAL_CLOSED)


def cancel(*, user: User, referral_id: UUID) -> None:
    """Take back a request that has not been answered."""
    with transaction.atomic():
        referral = _lock(user, referral_id)
        previous = referral.status
        if WORKFLOW.apply(referral, S.CANCELLED, actor=selectors.actor_for(user, referral)):
            _save_move(referral, previous, by=user, action="referral.cancelled")
            retract(recipient_id=referral.referrer_id, type=T.REFERRAL_REQUESTED, target=referral)
            _announce(referral, referral.referrer_id)


def refer(*, user: User, referral_id: UUID, endorsement_note: str) -> None:
    """Make the referral: from here the people hiring see it, with the referrer's note.

    The referrer vouches as a member of the organization, so they must still be one, and
    the job must still be taking applications. If the requester has already applied, the
    referral is attached to that application straight away.
    """
    with transaction.atomic():
        referral = _lock(user, referral_id)
        previous = referral.status
        actor = selectors.actor_for(user, referral)
        if previous == S.ACCEPTED and actor.is_referrer:
            opportunity = referral.opportunity
            if not selectors.is_active_member(user, opportunity):
                raise BusinessRuleViolation(
                    "You are no longer a member of this organization.", code="not_a_member"
                )
            if opportunity.status != OpportunityStatus.PUBLISHED or (
                opportunity.deadline is not None and opportunity.deadline <= timezone.now()
            ):
                raise Conflict(
                    BARRIER_MESSAGES[Barrier.NOT_ACCEPTING], code=Barrier.NOT_ACCEPTING.value
                )
        if WORKFLOW.apply(referral, S.REFERRED, actor=actor):
            referral.endorsement_note = endorsement_note
            referral.referred_at = timezone.now()
            _save_move(
                referral,
                previous,
                by=user,
                action="referral.referred",
                fields=("endorsement_note", "referred_at"),
            )
            notify(
                recipient=referral.requester,
                type=T.REFERRAL_REFERRED,
                target=referral,
                actor=user,
                payload=_about(referral),
            )
            _announce(referral, referral.requester_id)
            application = Application.objects.filter(
                opportunity_id=referral.opportunity_id, applicant_id=referral.requester_id
            ).first()
            if application is not None:
                _follow(referral, application)


# --- Following the application ----------------------------------------------------------


def _close(referral: ReferralRequest, *, tell_referrer: bool, tell_requester: bool) -> None:
    """Close a referral on the system's behalf. The row is locked by the caller."""
    previous = referral.status
    if not WORKFLOW.apply(referral, S.CLOSED, actor=None):
        return
    _save_move(referral, previous, by=None, action="referral.closed")
    if previous == S.REQUESTED:
        # The referrer never answered; the question simply goes away.
        retract(recipient_id=referral.referrer_id, type=T.REFERRAL_REQUESTED, target=referral)
    for recipient, wanted in (
        (referral.referrer, tell_referrer and previous != S.REQUESTED),
        (referral.requester, tell_requester),
    ):
        if wanted:
            notify(
                recipient=recipient,
                type=T.REFERRAL_CLOSED,
                target=referral,
                payload=_about(referral),
            )
    _announce(referral, referral.requester_id, referral.referrer_id)


def _follow(referral: ReferralRequest, application: Application) -> None:
    """Bring a made referral in line with the requester's application. Both rows are
    locked, or being created, by the caller's transaction."""
    if referral.application_id is None:
        referral.application = application
        referral.save(update_fields=["application", "updated_at"])
    target = MIRROR[application.status]
    if target == S.CLOSED:
        # The requester hears about their application from the application itself.
        _close(referral, tell_referrer=True, tell_requester=False)
        return
    previous = referral.status
    if WORKFLOW.apply(referral, target, actor=None):
        _save_move(referral, previous, by=None, action="referral.outcome")
        if target in _OUTCOMES_ANNOUNCED:
            notify(
                recipient=referral.referrer,
                type=T.REFERRAL_OUTCOME,
                target=referral,
                payload={**_about(referral), "status": target.value},
            )
        _announce(referral, referral.requester_id, referral.referrer_id)


def sync_from_application(application: Application) -> None:
    """Carry a change to an application over to the applicant's referrals for that job.

    Called by the application service inside the transaction that made the change; this is
    the only writer of a referral's status once the referral has been made, so the two
    cannot drift apart.

    Every open referral is locked, including those not yet made: someone making one at this
    moment then waits for this transaction, and finds the application when they continue.
    """
    referrals = (
        ReferralRequest.objects.select_for_update(of=("self",))
        .select_related("opportunity", "requester__profile", "referrer__profile")
        .filter(
            opportunity_id=application.opportunity_id,
            requester_id=application.applicant_id,
            status__in=policies.OPEN,
        )
    )
    ended = MIRROR[application.status] == S.CLOSED
    for referral in referrals:
        if referral.referred_at is not None:
            _follow(referral, application)
        elif ended:
            # Asked for, perhaps agreed to, but never made: there is nothing left to refer.
            _close(referral, tell_referrer=True, tell_requester=False)


# --- Sweeps -----------------------------------------------------------------------------


def _sweep(candidates: Q, still_due: Q, to: ReferralStatus) -> int:
    """Move each matching referral on the system's behalf, one transaction per row.

    The row is locked and re-checked before it is moved, so a person acting at the same
    moment wins cleanly and nothing is moved, audited or announced twice.
    """
    moved = 0
    ids = list(
        ReferralRequest.objects.filter(candidates)
        .order_by("expires_at")
        .values_list("pk", flat=True)[:SWEEP_BATCH]
    )
    for referral_id in ids:
        with transaction.atomic():
            referral = (
                ReferralRequest.objects.select_for_update(of=("self",))
                .select_related("opportunity", "requester__profile", "referrer__profile")
                .filter(still_due, pk=referral_id)
                .first()
            )
            if referral is None:
                continue
            if to == S.CLOSED:
                _close(referral, tell_referrer=True, tell_requester=True)
            else:
                previous = referral.status
                WORKFLOW.apply(referral, to, actor=None)
                _save_move(referral, previous, by=None, action="referral.expired")
                retract(
                    recipient_id=referral.referrer_id, type=T.REFERRAL_REQUESTED, target=referral
                )
                notify(
                    recipient=referral.requester,
                    type=T.REFERRAL_EXPIRED,
                    target=referral,
                    payload=_about(referral),
                )
                _announce(referral, referral.requester_id, referral.referrer_id)
            moved += 1
    return moved


def expire_unanswered() -> int:
    """Expire requests nobody answered in time. Safe to run at any time, any number of
    times."""
    due = Q(status=S.REQUESTED, expires_at__lt=timezone.now())
    return _sweep(due, due, S.EXPIRED)


def close_for_ended_jobs() -> int:
    """Close referrals that can no longer lead anywhere: the job stopped taking
    applications before the requester applied.

    A referral that already has an application is left alone. It goes on following that
    application, which can still be decided after the job has closed.
    """
    pending = Q(status__in=(S.REQUESTED, S.ACCEPTED, S.REFERRED), application__isnull=True)
    ended = ~Q(opportunity__status=OpportunityStatus.PUBLISHED) | Q(
        opportunity__deadline__lt=timezone.now()
    )
    return _sweep(pending & ended, pending & ended, S.CLOSED)
