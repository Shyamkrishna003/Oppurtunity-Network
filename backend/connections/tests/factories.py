from django.utils import timezone

from connections.models import Connection
from connections.selectors import ordered


def make_connection(requester, recipient, status="ACCEPTED") -> Connection:
    """The pair's row in the given state, as if ``requester`` had asked ``recipient``.

    Written directly (not through the services), so tests can start from any state.
    """
    low, high = ordered(requester.pk, recipient.pk)
    return Connection.objects.create(
        user_low_id=low,
        user_high_id=high,
        requested_by=requester,
        status=status,
        responded_at=None if status == "REQUESTED" else timezone.now(),
    )
