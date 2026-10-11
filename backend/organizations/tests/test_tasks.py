from smtplib import SMTPException

import pytest
from celery.exceptions import Retry
from django.core import mail

from organizations import services, tasks, tokens
from organizations.models import OrganizationInvitation
from organizations.tests.factories import organization_with_roles

pytestmark = pytest.mark.django_db


@pytest.fixture
def invitation():
    organization, members = organization_with_roles()
    return services.invite(
        actor=members["OWNER"].user,
        organization_id=organization.pk,
        email="new@example.com",
        role="RECRUITER",
    )


def test_invitation_email_names_the_inviter_role_and_link(invitation):
    tasks.send_invitation_email(str(invitation.pk))

    (message,) = mail.outbox
    inviter = invitation.invited_by.profile.display_name
    assert message.to == ["new@example.com"]
    assert f"{inviter} invited you to join {invitation.organization.name}" in message.body
    assert "as recruiter" in message.body
    link = f"http://app.test/organization-invitations/{tokens.invitation_token(invitation.pk)}"
    assert link in message.body


def test_names_are_not_html_escaped_in_the_plain_text_email(invitation):
    invitation.organization.name = "R&D <Labs>"
    invitation.organization.save()

    tasks.send_invitation_email(str(invitation.pk))

    assert "R&D <Labs>" in mail.outbox[0].body


def test_no_email_for_an_invitation_that_is_no_longer_open(invitation):
    OrganizationInvitation.objects.update(status="REVOKED")

    tasks.send_invitation_email(str(invitation.pk))

    assert mail.outbox == []


def test_invitation_email_retries_when_the_mail_server_fails(invitation, monkeypatch):
    def fail(**kwargs):
        raise SMTPException("mail server down")

    monkeypatch.setattr(tasks, "send_templated", fail)

    with pytest.raises(Retry):
        tasks.send_invitation_email.apply(args=[str(invitation.pk)], throw=True)
