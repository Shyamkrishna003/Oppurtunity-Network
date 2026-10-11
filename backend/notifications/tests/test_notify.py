from datetime import timedelta
from smtplib import SMTPException

import pytest
from celery.exceptions import Retry
from django.core import mail
from django.db import transaction
from django.utils import timezone
from kombu.exceptions import OperationalError

from communities.tests.factories import CommunityFactory
from notifications import catalog, services, tasks
from notifications.models import (
    Category,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationType,
)
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

T = NotificationType


def tell(recipient, type=T.COMMUNITY_JOIN_APPROVED, **overrides):
    community = overrides.pop("target", None) or CommunityFactory(name="Kochi Developers")
    payload = {"community_id": str(community.pk), "community_name": community.name}
    return services.notify(
        recipient=recipient, type=type, target=community, payload=payload, **overrides
    )


def prefer(user, category, *, in_app, email):
    NotificationPreference.objects.create(user=user, category=category, in_app=in_app, email=email)


# --- notify() ---------------------------------------------------------------------------


def test_notify_stores_the_notification_and_queues_its_email(django_capture_on_commit_callbacks):
    recipient, actor = UserFactory(), UserFactory()

    with django_capture_on_commit_callbacks(execute=True):
        notification = tell(recipient, actor=actor)

    assert (notification.recipient, notification.actor, notification.in_app) == (
        recipient,
        actor,
        True,
    )
    assert (notification.target_type, notification.read_at) == ("communities.community", None)
    (message,) = mail.outbox
    assert message.to == [recipient.email]
    assert message.subject == "You are now a member of Kochi Developers"
    assert f"http://app.test/communities/{notification.target_id}" in message.body
    assert "http://app.test/settings/notifications" in message.body
    assert NotificationDelivery.objects.get().status == "SENT"


def test_the_email_is_only_queued_once_the_change_is_committed():
    recipient = UserFactory()

    with pytest.raises(RuntimeError), transaction.atomic():
        tell(recipient)
        raise RuntimeError("the change being reported failed")

    # Rolled back with the change it was about: no notification, no delivery, no email.
    assert not Notification.objects.exists()
    assert not NotificationDelivery.objects.exists()
    assert mail.outbox == []


@pytest.mark.parametrize(
    ("in_app", "email", "stored", "listed", "emailed"),
    [
        (True, True, True, True, True),
        (True, False, True, True, False),
        (False, True, True, False, True),  # kept for the email, hidden from the list
        (False, False, False, False, False),
    ],
)
def test_preferences_decide_each_channel(
    django_capture_on_commit_callbacks, in_app, email, stored, listed, emailed
):
    recipient = UserFactory()
    prefer(recipient, Category.MEMBERSHIP, in_app=in_app, email=email)

    with django_capture_on_commit_callbacks(execute=True):
        tell(recipient)

    assert Notification.objects.exists() is stored
    assert services.list_for(recipient).exists() is listed
    assert services.unread_count(recipient) == (1 if listed else 0)
    assert bool(mail.outbox) is emailed


def test_a_preference_for_one_category_leaves_the_others_on_their_defaults():
    recipient = UserFactory()
    prefer(recipient, Category.POSTINGS, in_app=False, email=False)

    assert tell(recipient) is not None  # MEMBERSHIP is untouched
    assert services.preferences_for(recipient) == {
        **catalog.DEFAULTS,
        Category.POSTINGS: (False, False),
    }


def test_review_notifications_are_not_emailed_by_default(django_capture_on_commit_callbacks):
    recipient = UserFactory()
    community = CommunityFactory()
    payload = {
        "community_id": str(community.pk),
        "community_name": community.name,
        "person_name": "Ada",
    }

    with django_capture_on_commit_callbacks(execute=True):
        services.notify(
            recipient=recipient, type=T.COMMUNITY_JOIN_REQUESTED, target=community, payload=payload
        )

    assert Notification.objects.count() == 1
    assert mail.outbox == []


def test_types_with_their_own_email_never_get_a_second_one(django_capture_on_commit_callbacks):
    recipient = UserFactory()
    payload = {"community_id": "x", "community_name": "Kochi Developers", "inviter_name": "Ada"}

    with django_capture_on_commit_callbacks(execute=True):
        services.notify(
            recipient=recipient,
            type=T.COMMUNITY_INVITATION,
            target=CommunityFactory(),
            payload=payload,
        )

    assert Notification.objects.count() == 1
    assert not NotificationDelivery.objects.exists()


def test_nobody_is_notified_about_their_own_action_or_when_deactivated():
    person = UserFactory()

    assert tell(person, actor=person) is None
    assert tell(UserFactory(is_active=False)) is None
    assert not Notification.objects.exists()


def test_email_only_goes_to_a_confirmed_address(django_capture_on_commit_callbacks):
    recipient = UserFactory(unverified=True)

    with django_capture_on_commit_callbacks(execute=True):
        notification = tell(recipient)

    assert notification is not None  # still shown in the app
    assert not NotificationDelivery.objects.exists()
    assert mail.outbox == []


def test_a_dedupe_key_notifies_once_without_breaking_the_callers_transaction():
    recipient, other = UserFactory(), UserFactory()
    community = CommunityFactory()

    with transaction.atomic():
        first = tell(recipient, target=community, dedupe_key="expired:1")
        again = tell(recipient, target=community, dedupe_key="expired:1")
        # The duplicate was refused inside a savepoint, so the transaction is still usable.
        for_another = tell(other, target=community, dedupe_key="expired:1")
        different = tell(recipient, target=community, dedupe_key="expired:2")

    assert first is not None and again is None
    assert for_another is not None and different is not None
    assert Notification.objects.filter(recipient=recipient).count() == 2


def test_notify_each_counts_who_was_told():
    actor = UserFactory()
    people = [UserFactory(), UserFactory(), actor, UserFactory(is_active=False)]
    community = CommunityFactory()

    told = services.notify_each(
        people,
        type=T.COMMUNITY_JOIN_APPROVED,
        target=community,
        actor=actor,
        payload={"community_id": str(community.pk), "community_name": community.name},
    )

    assert told == 2


def test_a_broker_outage_does_not_fail_the_change(monkeypatch, django_capture_on_commit_callbacks):
    def fail(*args, **kwargs):
        raise OperationalError("broker down")

    monkeypatch.setattr(tasks.send_notification_email, "delay", fail)

    with django_capture_on_commit_callbacks(execute=True):
        notification = tell(UserFactory())

    # Stored and still pending: the redispatch sweep will pick it up.
    assert notification is not None
    assert NotificationDelivery.objects.get().status == "PENDING"


# --- The catalogue ----------------------------------------------------------------------


def test_every_type_has_a_spec_and_every_category_a_default_and_description():
    assert set(catalog.SPECS) == set(NotificationType)
    assert set(catalog.DEFAULTS) == set(Category) == set(catalog.DESCRIPTIONS)


SAMPLE = {
    "organization_id": "o-1",
    "organization_name": "Example Labs",
    "community_id": "c-1",
    "community_name": "Kochi Developers",
    "opportunity_id": "p-1",
    "opportunity_title": "Backend Engineer",
    "application_id": "a-1",
    "person_name": "Ada Lovelace",
    "inviter_name": "Grace Hopper",
    "role_label": "recruiter",
    "reason": "Off topic.",
}


@pytest.mark.parametrize("type", list(NotificationType))
def test_every_type_can_be_worded(type):
    notification = Notification(
        type=type, payload=SAMPLE, target_id="0199b7c0-0000-7000-8000-000000000000"
    )

    rendered = catalog.render(notification)

    assert rendered.title and rendered.body
    assert rendered.url.startswith("/")
    assert "{" not in rendered.title + rendered.body + rendered.url  # no unfilled placeholder


def test_a_rejection_shows_its_reason_only_when_one_was_given():
    def body(reason):
        payload = {**SAMPLE, "reason": reason}
        return catalog.render(Notification(type=T.SHARE_REJECTED, payload=payload)).body

    assert "Reason given: Off topic." in body("Off topic.")
    assert "Reason given" not in body("")


# --- Email delivery ---------------------------------------------------------------------


@pytest.fixture
def pending():
    """A notification whose email has not been sent yet."""
    notification = tell(UserFactory())
    return NotificationDelivery.objects.get(notification=notification)


def test_sending_twice_emails_once(pending):
    assert tasks.send_notification_email(str(pending.pk)) == "sent"
    assert tasks.send_notification_email(str(pending.pk)) == "nothing to do"

    assert len(mail.outbox) == 1
    pending.refresh_from_db()
    assert (pending.status, pending.attempts) == ("SENT", 1)
    assert pending.sent_at is not None


def test_a_mail_failure_leaves_the_delivery_pending_and_retries(pending, monkeypatch):
    def fail(**kwargs):
        raise SMTPException("mail server down")

    monkeypatch.setattr(tasks, "send_templated", fail)

    with pytest.raises(Retry):
        tasks.send_notification_email.apply(args=[str(pending.pk)], throw=True)

    pending.refresh_from_db()
    assert pending.status == "PENDING"
    assert pending.attempts >= 1
    assert mail.outbox == []


@pytest.mark.parametrize("change", [{"is_active": False}, {"email_verified_at": None}])
def test_the_email_is_skipped_if_the_recipient_can_no_longer_receive_it(pending, change):
    type(pending.notification.recipient).objects.filter(
        pk=pending.notification.recipient_id
    ).update(**change)

    assert tasks.send_notification_email(str(pending.pk)) == "skipped"
    pending.refresh_from_db()
    assert pending.status == "SKIPPED"
    assert mail.outbox == []


def age(delivery, **delta):
    NotificationDelivery.objects.filter(pk=delivery.pk).update(
        created_at=timezone.now() - timedelta(**delta)
    )


def test_redispatch_sends_what_was_left_pending(pending):
    """As after a broker outage or a worker restart: the row is there, the message is not."""
    assert tasks.redispatch_pending() == 0  # too recent: the normal path may still be working
    age(pending, minutes=10)

    assert tasks.redispatch_pending() == 1

    assert len(mail.outbox) == 1
    pending.refresh_from_db()
    assert pending.status == "SENT"
    assert tasks.redispatch_pending() == 0


def test_redispatch_gives_up_after_too_many_attempts(pending):
    age(pending, minutes=10)
    NotificationDelivery.objects.filter(pk=pending.pk).update(attempts=tasks.MAX_ATTEMPTS)

    assert tasks.redispatch_pending() == 0

    pending.refresh_from_db()
    assert pending.status == "FAILED"
    assert mail.outbox == []


def test_purge_removes_only_old_read_notifications():
    recipient = UserFactory()
    old_read, old_unread, recent_read = (tell(recipient) for _ in range(3))
    long_ago = timezone.now() - timedelta(days=120)
    Notification.objects.filter(pk=old_read.pk).update(read_at=long_ago)
    Notification.objects.filter(pk=old_unread.pk).update(created_at=long_ago)
    Notification.objects.filter(pk=recent_read.pk).update(read_at=timezone.now())

    assert tasks.purge_old() >= 1
    assert set(Notification.objects.values_list("pk", flat=True)) == {old_unread.pk, recent_read.pk}
