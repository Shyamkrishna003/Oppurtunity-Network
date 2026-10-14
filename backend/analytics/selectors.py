"""Counts across the platform. Every number is computed by the database, never in Python."""

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db.models import (
    Aggregate,
    Count,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from analytics import policies
from analytics.models import DailyOpportunityViews
from applications.models import Application, ApplicationStatus
from communities.models import Community
from events.models import EventRegistration, RegistrationStatus
from moderation.models import Report, ReportStatus
from opportunities.models import (
    ModerationStatus,
    Opportunity,
    OpportunityStatus,
    OpportunityType,
    SavedOpportunity,
)
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


# --- One opportunity's numbers ----------------------------------------------------------

# The counted columns of ``OpportunityStats``, in the order they are computed.
NUMBERS = ("views", "recent_views", "saves", "applications", "registrations", "referrals")


def _per_opportunity(rows: QuerySet[Any], link: str, total: Aggregate) -> Coalesce:
    """A correlated subquery: ``total`` over the ``rows`` that belong to the outer
    opportunity through ``link``. Zero when there are none."""
    one = rows.filter(**{link: OuterRef("pk")}).order_by().values(link).annotate(n=total)
    return Coalesce(Subquery(one.values("n"), output_field=IntegerField()), 0)


def numbers_for(opportunity_ids: Iterable[UUID]) -> dict[UUID, dict[str, int]]:
    """Every counted number for each of the given opportunities, in one query.

    The only place these are worked out: the stored stats and what a manager is shown both
    come from here, so they cannot disagree about what counts.
    """
    since = timezone.localdate() - policies.RECENT
    daily = DailyOpportunityViews.objects.all()
    counted = Opportunity.objects.filter(pk__in=list(opportunity_ids)).annotate(
        n_views=_per_opportunity(daily, "opportunity", Sum("views")),
        n_recent_views=_per_opportunity(daily.filter(date__gte=since), "opportunity", Sum("views")),
        n_saves=_per_opportunity(SavedOpportunity.objects.all(), "opportunity", Count("pk")),
        n_applications=_per_opportunity(Application.objects.all(), "opportunity", Count("pk")),
        # A registration's event has the opportunity's own id. Only places still held.
        n_registrations=_per_opportunity(
            EventRegistration.objects.filter(status=RegistrationStatus.CONFIRMED),
            "event",
            Count("pk"),
        ),
        n_referrals=_per_opportunity(
            ReferralRequest.objects.filter(status__in=_REFERRED), "opportunity", Count("pk")
        ),
    )
    return {
        row["pk"]: {name: row[f"n_{name}"] for name in NUMBERS}
        for row in counted.values("pk", *(f"n_{name}" for name in NUMBERS))
    }


def views_by_day(opportunity_id: UUID, days: int) -> list[tuple[date, int]]:
    """Views on each of the last ``days`` days, oldest first, with zero for quiet days."""
    today = timezone.localdate()
    first = today - timedelta(days=days - 1)
    seen = dict(
        DailyOpportunityViews.objects.filter(
            opportunity_id=opportunity_id, date__gte=first
        ).values_list("date", "views")
    )
    return [(day, seen.get(day, 0)) for day in (first + timedelta(days=n) for n in range(days))]
