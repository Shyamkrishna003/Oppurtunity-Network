from smtplib import SMTPException

import pytest
from celery.exceptions import Retry
from django.core import mail

from communities import tasks
from communities.models import CommunityMember
from communities.tests.factories import CommunityMemberFactory, community_with_roles

pytestmark = pytest.mark.django_db


@pytest.fixture
def invited():
    community, members = community_with_roles(name="R&D <Circle>")
    return CommunityMemberFactory(
        community=community, status="INVITED", invited_by=members["OWNER"].user
    )


def test_invitation_email_names_the_inviter_and_links_to_the_community(invited):
    tasks.send_invitation_email(str(invited.pk))

    (message,) = mail.outbox
    inviter = invited.invited_by.profile.display_name
    assert message.to == [invited.user.email]
    # Plain text: names are not HTML-escaped.
    assert f"{inviter} invited you to join the community R&D <Circle>" in message.body
    assert f"http://app.test/communities/{invited.community_id}" in message.body


def test_no_email_once_the_invitation_is_answered_or_withdrawn(invited):
    CommunityMember.objects.filter(pk=invited.pk).update(status="REMOVED")

    tasks.send_invitation_email(str(invited.pk))

    assert mail.outbox == []


def test_invitation_email_retries_when_the_mail_server_fails(invited, monkeypatch):
    def fail(**kwargs):
        raise SMTPException("mail server down")

    monkeypatch.setattr(tasks, "send_templated", fail)

    with pytest.raises(Retry):
        tasks.send_invitation_email.apply(args=[str(invited.pk)], throw=True)
