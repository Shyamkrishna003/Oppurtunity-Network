"""Counts across the platform. Every number is computed by the database, never in Python."""

from datetime import timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from applications.models import Application, ApplicationStatus
from communities.models import Community
from events.models import EventRegistration, RegistrationStatus
from moderation.models import Report, ReportStatus
from opportunities.models import ModerationStatus, Opportunity, OpportunityStatus, OpportunityType
from organizations.models import Organization, VerificationStatus
from referrals.models import ReferralRequest, ReferralStatus
from users.models import User

_CACHE_KEY = "analytics:platform-totals"
# Long enough that a dashboard left open costs nothing; short enough to feel current.
CACHE_SECONDS = 60
RECENT = timedelta(days=7)

# A referral counts as made once the referrer has put their name to it.
_REFERRED = (
    ReferralStatus.REFERRED,
    ReferralStatus.APPLICATION_SUBMITTED,
    ReferralStatus.INTERVIEW,
    ReferralStatus.OFFER,
    ReferralStatus.JOINED,
)


def _count(**conditions: Any) -> Count:
    return Count("pk", filter=Q(**conditions))


def _compute() -> dict[str, Any]:
    now = timezone.now()
    since = now - RECENT
    published = {
        "status": OpportunityStatus.PUBLISHED,
        "moderation_status": ModerationStatus.VISIBLE,
    }
    return {
        "generated_at": now,
        "users": User.objects.aggregate(
            total=Count("pk"),
            verified=_count(email_verified_at__isnull=False),
            joined_recently=_count(created_at__gte=since),
            suspended=_count(suspended_until__gt=now),
        ),
        "organizations": Organization.objects.aggregate(
            total=Count("pk"),
            verified=_count(verification_status=VerificationStatus.VERIFIED),
        ),
        "communities": Community.objects.aggregate(total=Count("pk")),
        "opportunities": Opportunity.objects.aggregate(
            published=_count(**published),
            jobs=_count(**published, type=OpportunityType.JOB),
            events=_count(**published, type=OpportunityType.EVENT),
            published_recently=_count(published_at__gte=since),
            hidden_or_removed=Count("pk", filter=~Q(moderation_status=ModerationStatus.VISIBLE)),
        ),
        # What the platform is for: things that happened to people, not how much they clicked.
        "outcomes": {
            **Application.objects.aggregate(
                applications=Count("pk"), hires=_count(status=ApplicationStatus.HIRED)
            ),
            **EventRegistration.objects.aggregate(
                registrations=_count(status=RegistrationStatus.CONFIRMED),
                attendances=_count(checked_in_at__isnull=False),
            ),
            **ReferralRequest.objects.aggregate(
                referrals=_count(status__in=_REFERRED),
                referral_joins=_count(status=ReferralStatus.JOINED),
            ),
        },
        "reports": Report.objects.aggregate(
            waiting=_count(status=ReportStatus.OPEN),
            under_review=_count(status=ReportStatus.UNDER_REVIEW),
        ),
    }


def platform_totals() -> dict[str, Any]:
    """The numbers on the admin dashboard, at most a minute old."""
    totals: dict[str, Any] | None = cache.get(_CACHE_KEY)
    if totals is None:
        totals = _compute()
        cache.set(_CACHE_KEY, totals, CACHE_SECONDS)
    return totals
