from smtplib import SMTPException

from celery import shared_task

from common.email import send_templated
from organizations import tokens
from organizations.models import InvitationStatus, OrganizationInvitation


@shared_task(
    name="organizations.send_invitation_email",
    queue="email",
    autoretry_for=(SMTPException, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=6,
)
def send_invitation_email(invitation_id: str) -> None:
    """Email the invitation link. A retry may send it twice; both copies carry the same link."""
    invitation = (
        OrganizationInvitation.objects.select_related("organization", "invited_by__profile")
        .filter(pk=invitation_id, status=InvitationStatus.PENDING)
        .first()
    )
    if invitation is None:
        return
    inviter = invitation.invited_by.profile.display_name if invitation.invited_by else "Someone"
    send_templated(
        to=invitation.email,
        subject=f"You are invited to join {invitation.organization.name}",
        template="organizations/email/invitation.txt",
        context={
            "organization": invitation.organization.name,
            "inviter": inviter,
            "role": invitation.get_role_display().lower(),
            "path": f"/organization-invitations/{tokens.invitation_token(invitation.pk)}",
        },
    )
