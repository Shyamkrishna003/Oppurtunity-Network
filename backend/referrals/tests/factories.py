from datetime import timedelta

from django.utils import timezone

from connections.tests.factories import make_connection
from opportunities.tests.factories import make_job
from organizations.tests.factories import MemberFactory, organization_with_roles
from referrals.models import ReferralRequest, ReferralStatusHistory
from users.tests.factories import UserFactory


def referral_setup(**job_fields):
    """A published job at an organization, someone looking for a way in, and a connection
    of theirs who works there.

    Returns ``(job, people)``; ``people`` has ``requester``, ``referrer`` and the
    organization's ``OWNER`` and ``RECRUITER``.
    """
    organization, members = organization_with_roles("RECRUITER")
    job = make_job(
        status="PUBLISHED",
        organization=organization,
        creator=members["RECRUITER"].user,
        **job_fields,
    )
    requester = UserFactory(display_name="Rita Requester")
    referrer = colleague(job, requester, display_name="Ravi Referrer")
    people = {
        "requester": requester,
        "referrer": referrer,
        "OWNER": members["OWNER"].user,
        "RECRUITER": members["RECRUITER"].user,
    }
    return job, people


def colleague(job, requester, *, connected=True, **user_fields):
    """A member of the job's organization, connected to ``requester`` unless told otherwise."""
    user = UserFactory(**user_fields)
    MemberFactory(organization=job.organization, user=user)
    if connected:
        make_connection(requester, user)
    return user


def make_referral(job, requester, referrer, status="REQUESTED", **fields) -> ReferralRequest:
    """A referral in the given state. Written directly (not through the services), so tests
    can start from any state."""
    now = timezone.now()
    made = status in ("REFERRED", "APPLICATION_SUBMITTED", "INTERVIEW", "OFFER", "JOINED")
    fields.setdefault("expires_at", now + timedelta(days=14))
    if made:
        fields.setdefault("referred_at", now)
        fields.setdefault("endorsement_note", "I worked with them for two years.")
    referral = ReferralRequest.objects.create(
        opportunity=job,
        requester=requester,
        referrer=referrer,
        status=status,
        status_changed_at=now,
        **fields,
    )
    ReferralStatusHistory.objects.create(referral=referral, to_status="REQUESTED", actor=requester)
    return referral
