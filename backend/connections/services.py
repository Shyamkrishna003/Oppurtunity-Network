"""Every write to connections."""

from functools import partial
from uuid import UUID

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from common.errors import BusinessRuleViolation, Conflict
from common.tasks import enqueue
from connections import policies, selectors
from connections.models import Connection, ConnectionStatus
from connections.policies import ANSWERS
from notifications.models import NotificationType
from notifications.services import notify, retract
from realtime.tasks import publish_event
from users.models import User
from users.selectors import is_blocked_either_way

S = ConnectionStatus


def _announce(user_id: UUID, connection: Connection) -> None:
    """Tell one person's open pages that their connections changed. Only a hint: the pages
    refetch through the API. Never sent for a decline, which is not announced."""
    transaction.on_commit(
        partial(
            enqueue, publish_event, str(user_id), "connection.updated", {"id": str(connection.pk)}
        )
    )


def _create(user: User, other: User) -> Connection | None:
    low, high = selectors.ordered(user.pk, other.pk)
    try:
        # A savepoint, so losing the race does not poison the caller's transaction.
        with transaction.atomic():
            return Connection.objects.create(user_low_id=low, user_high_id=high, requested_by=user)
    except IntegrityError:
        return None


def request(*, user: User, user_id: UUID) -> tuple[Connection, bool]:
    """Ask someone to connect. Returns the pair's row and whether this call created it.

    Asking again while a request is out is not an error and tells nobody anything new: the
    request already there is returned. That is also what happens after the other person
    declined, since a decline is not announced.

    Someone who has blocked the caller, or whom the caller blocked, looks like someone who
    does not exist.
    """
    if user_id == user.pk:
        raise BusinessRuleViolation("You cannot connect with yourself.", code="cannot_connect_self")
    other = User.objects.select_related("profile").filter(pk=user_id, is_active=True).first()
    if other is None or is_blocked_either_way(user, other):
        raise Http404

    with transaction.atomic():
        existing = selectors.between(user.pk, other.pk).select_for_update().first()
        if existing is not None:
            if existing.status == S.ACCEPTED:
                raise Conflict("You are already connected.", code="already_connected")
            if existing.requested_by_id == user.pk:
                return existing, False
            if existing.status == S.REQUESTED:
                raise Conflict(
                    "This person has already asked to connect with you. Answer their request.",
                    code="request_waiting",
                )
            # The caller declined this person earlier and now asks them: a new request, in
            # the other direction.
            existing.delete()

        connection = _create(user, other)
        if connection is None:
            # Someone stored the pair's row first, a moment ago: the caller's own second
            # click, or the other person asking at the same instant.
            winner = selectors.between(user.pk, other.pk).first()
            if winner is not None and winner.requested_by_id == user.pk:
                return winner, False
            raise Conflict(
                "This person has just asked to connect with you. Answer their request.",
                code="request_waiting",
            )
        notify(
            recipient=other,
            type=NotificationType.CONNECTION_REQUESTED,
            target=connection,
            actor=user,
            payload={"person_name": user.profile.display_name},
        )
        _announce(other.pk, connection)
    return connection, True


def _lock(user: User, connection_id: UUID) -> Connection:
    connection = (
        selectors.visible_to(user)
        .select_for_update(of=("self",))
        .select_related("user_low__profile", "user_high__profile")
        .filter(pk=connection_id)
        .first()
    )
    if connection is None:
        raise Http404
    return connection


def respond(*, user: User, connection_id: UUID, accept: bool) -> Connection:
    """Accept or decline a request, as the person who was asked. Accepting twice changes
    nothing; an answer cannot be changed, and a declined request is gone for whoever
    declined it (404)."""
    with transaction.atomic():
        connection = _lock(user, connection_id)
        party = policies.party_for(user.pk, connection)
        # Checked before the state, so that whoever asked learns nothing from trying to
        # answer their own request: not even whether it was declined.
        if not party.is_recipient:
            raise PermissionDenied()
        if ANSWERS.apply(connection, S.ACCEPTED if accept else S.DECLINED, actor=party):
            connection.responded_at = timezone.now()
            connection.save(update_fields=["status", "responded_at", "updated_at"])
            if accept:
                notify(
                    recipient=connection.requested_by,
                    type=NotificationType.CONNECTION_ACCEPTED,
                    target=connection,
                    actor=user,
                    payload={"person_name": user.profile.display_name},
                )
                _announce(connection.requested_by_id, connection)
        return connection


def _delete(connection: Connection) -> None:
    """Remove the row, and the notification of a request that no longer exists."""
    if connection.status == S.REQUESTED:
        recipient_id = connection.other_id(connection.requested_by_id)
        retract(
            recipient_id=recipient_id,
            type=NotificationType.CONNECTION_REQUESTED,
            target=connection,
        )
    connection.delete()


def remove(*, user: User, connection_id: UUID) -> None:
    """End a connection, or take back a request one made."""
    with transaction.atomic():
        connection = _lock(user, connection_id)
        if not policies.can_remove(user.pk, connection):
            raise Conflict("Accept or decline this request instead.", code="answer_instead")
        # The other person is told unless they declined: to them the row was already gone.
        if connection.status != S.DECLINED:
            _announce(connection.other_id(user.pk), connection)
        _delete(connection)


def sever(first: User, second: User) -> None:
    """Remove whatever stands between two people, when one blocks the other. Call inside
    the transaction that records the block."""
    for connection in selectors.between(first.pk, second.pk).select_for_update():
        _delete(connection)
