"""Creating, reading and configuring notifications.

Other apps call ``notify()`` from inside the transaction that makes the change being
reported. The notification row is therefore committed or rolled back together with that
change, and is the durable record; the email (and, later, the push to an open browser) is
only queued once the transaction has committed, and can be retried or lost without losing
the notification.
"""

from collections.abc import Iterable, Mapping
from functools import partial
from typing import Any
from uuid import UUID

from django.db import IntegrityError, models, transaction
from django.http import Http404
from django.utils import timezone

from common.tasks import enqueue
from notifications import tasks
from notifications.catalog import DEFAULTS, SPECS
from notifications.models import (
    Category,
    Channel,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationType,
)
from realtime.tasks import publish_event
from users.models import User

Preference = tuple[bool, bool]  # (in the app, by email)


def preferences_for(user: User) -> dict[Category, Preference]:
    """The person's choice for every category, with defaults where they made none."""
    chosen = {
        Category(category): (in_app, email)
        for category, in_app, email in NotificationPreference.objects.filter(user=user).values_list(
            "category", "in_app", "email"
        )
    }
    return {category: chosen.get(category, default) for category, default in DEFAULTS.items()}


def _preference(user: User, category: Category) -> Preference:
    row = (
        NotificationPreference.objects.filter(user=user, category=category)
        .values_list("in_app", "email")
        .first()
    )
    return row if row is not None else DEFAULTS[category]


def notify(
    *,
    recipient: User,
    type: NotificationType,
    target: models.Model,
    actor: User | None = None,
    payload: Mapping[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    """Tell ``recipient`` that something happened. Call inside the change's transaction.

    Returns the notification, or ``None`` when there is nothing to send: the recipient did
    it themselves, has switched this category off, is deactivated, or (with ``dedupe_key``)
    was already told.
    """
    if not recipient.is_active or (actor is not None and actor.pk == recipient.pk):
        return None
    spec = SPECS[type]
    in_app, by_email = _preference(recipient, spec.category)
    # Email only goes to an address its owner has confirmed.
    by_email = by_email and spec.emailable and recipient.is_email_verified
    if not in_app and not by_email:
        return None

    fields = {
        "recipient": recipient,
        "type": type,
        "actor": actor,
        "target_type": target._meta.label_lower,
        "target_id": target.pk,
        "payload": dict(payload or {}),
        "dedupe_key": dedupe_key,
        "in_app": in_app,
    }
    if dedupe_key is None:
        notification = Notification.objects.create(**fields)
    else:
        try:
            # A savepoint, so a duplicate does not poison the caller's transaction.
            with transaction.atomic():
                notification = Notification.objects.create(**fields)
        except IntegrityError:
            return None

    if in_app:
        # Best-effort: if this push is lost, the notification is still in the list.
        transaction.on_commit(partial(enqueue, tasks.push_notification, str(notification.pk)))
    if by_email:
        delivery = NotificationDelivery.objects.create(
            notification=notification, channel=Channel.EMAIL
        )
        transaction.on_commit(partial(enqueue, tasks.send_notification_email, str(delivery.pk)))
    return notification


def notify_each(recipients: Iterable[User], **notification: Any) -> int:
    """``notify()`` for several people about the same thing. Returns how many were told.

    For small, bounded audiences (a community's reviewers). Anything that could reach a
    whole membership must be a chunked background job instead.
    """
    return sum(notify(recipient=recipient, **notification) is not None for recipient in recipients)


# --- Reading ----------------------------------------------------------------------------


def list_for(user: User, *, unread_only: bool = False) -> models.QuerySet[Notification]:
    notifications = Notification.objects.filter(recipient=user, in_app=True).select_related(
        "actor__profile"
    )
    if unread_only:
        notifications = notifications.filter(read_at__isnull=True)
    return notifications


def unread_count(user: User) -> int:
    return Notification.objects.filter(recipient=user, in_app=True, read_at__isnull=True).count()


def mark_read(*, user: User, notification_id: UUID) -> None:
    """Mark one of the user's own notifications as read. Doing it twice changes nothing."""
    own = Notification.objects.filter(pk=notification_id, recipient=user, in_app=True)
    if not own.exists():
        raise Http404
    if own.filter(read_at__isnull=True).update(read_at=timezone.now()):
        _announce_read(user, {"ids": [str(notification_id)]})


def mark_all_read(*, user: User) -> int:
    marked = Notification.objects.filter(recipient=user, in_app=True, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    if marked:
        _announce_read(user, {"all": True})
    return marked


def _announce_read(user: User, data: dict[str, Any]) -> None:
    """Tell the user's other tabs and devices, so their unread badges agree."""
    transaction.on_commit(partial(enqueue, publish_event, str(user.pk), "notification.read", data))


# --- Preferences ------------------------------------------------------------------------


def set_preferences(*, user: User, choices: Mapping[Category, Preference]) -> None:
    """Record the person's choice for the given categories; the others are left as they are."""
    with transaction.atomic():
        for category, (in_app, email) in choices.items():
            NotificationPreference.objects.update_or_create(
                user=user, category=category, defaults={"in_app": in_app, "email": email}
            )
