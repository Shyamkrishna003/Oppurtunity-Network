from smtplib import SMTPException

from celery import shared_task

from common.email import send_templated
from communities.models import CommunityMember, MemberStatus


@shared_task(
    name="communities.send_invitation_email",
    queue="email",
    autoretry_for=(SMTPException, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=6,
)
def send_invitation_email(member_id: str) -> None:
    """Tell a user they were invited. The link needs no secret: only the invited account,
    once signed in, can see the community and accept."""
    member = (
        CommunityMember.objects.select_related("community", "user", "invited_by__profile")
        .filter(pk=member_id, status=MemberStatus.INVITED, user__is_active=True)
        .first()
    )
    if member is None:
        return
    inviter = member.invited_by.profile.display_name if member.invited_by else "Someone"
    send_templated(
        to=member.user.email,
        subject=f"You are invited to join {member.community.name}",
        template="communities/email/invitation.txt",
        context={
            "community": member.community.name,
            "inviter": inviter,
            "path": f"/communities/{member.community_id}",
        },
    )
