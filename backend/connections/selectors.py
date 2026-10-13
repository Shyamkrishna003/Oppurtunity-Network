"""Read queries for connections. Views load objects only through these.

Every query here starts from one person and returns only rows they are part of. There is no
way to ask whom somebody else is connected to.
"""

from uuid import UUID

from django.db.models import Q, QuerySet
from django.http import Http404

from connections.models import Connection, ConnectionStatus
from connections.policies import State
from users.models import User

S = ConnectionStatus


def ordered(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    """The pair in the order it is stored: smaller ID first."""
    return (first, second) if first < second else (second, first)


def between(first: UUID, second: UUID) -> QuerySet[Connection]:
    """The pair's row, in whatever state: at most one."""
    low, high = ordered(first, second)
    return Connection.objects.filter(user_low_id=low, user_high_id=high)


def are_connected(first: User, second: User) -> bool:
    return between(first.pk, second.pk).filter(status=S.ACCEPTED).exists()


def _involving(user: User) -> Q:
    return Q(user_low=user) | Q(user_high=user)


def in_state(user: User, state: State) -> Q:
    """Rows that are in ``state`` from this person's side. See ``policies.state_for``."""
    if state is State.CONNECTED:
        return _involving(user) & Q(status=S.ACCEPTED)
    if state is State.INCOMING:
        return _involving(user) & Q(status=S.REQUESTED) & ~Q(requested_by=user)
    return Q(requested_by=user, status__in=(S.REQUESTED, S.DECLINED))


def visible_to(user: User) -> QuerySet[Connection]:
    """Every row that is something to this person: their connections and the requests on
    either side, minus the requests they declined."""
    return Connection.objects.filter(_involving(user)).exclude(
        ~Q(requested_by=user), status=S.DECLINED
    )


def list_for(user: User, state: State) -> QuerySet[Connection]:
    """The person's connections or requests, newest first, with both people's cards loaded.

    Someone whose account was deactivated drops out of the lists; the row stays, so the
    connection is there again if they come back.
    """
    return Connection.objects.filter(
        in_state(user, state), user_low__is_active=True, user_high__is_active=True
    ).select_related("user_low__profile", "user_high__profile")


def get_connection(user: User, connection_id: UUID) -> Connection:
    """The row if it is something to the user, else 404."""
    connection = (
        visible_to(user)
        .select_related("user_low__profile", "user_high__profile")
        .filter(pk=connection_id)
        .first()
    )
    if connection is None:
        raise Http404
    return connection


def with_user(viewer: User, other: User) -> Connection | None:
    """What stands between the viewer and one other person, as far as the viewer may know."""
    low, high = ordered(viewer.pk, other.pk)
    return visible_to(viewer).filter(user_low_id=low, user_high_id=high).first()


def incoming_count(user: User) -> int:
    return Connection.objects.filter(
        in_state(user, State.INCOMING), user_low__is_active=True, user_high__is_active=True
    ).count()
