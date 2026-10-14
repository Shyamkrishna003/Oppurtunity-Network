"""Funnels: how many got how far. Each is one aggregate query over a set of opportunities,
so the same code answers for one opportunity or for everything an organization posted.

A step counts everyone who *reached* it, whatever happened to them afterwards: an applicant
who was interviewed and then turned down still reached the interview. That is read from the
status histories, which keep every move.
"""

from dataclasses import dataclass
from typing import Any

from django.db.models import Count, Q, QuerySet, Sum

from analytics.models import DailyOpportunityViews
from applications.models import Application
from applications.policies import STAGES
from communities.models import Community, CommunityMember, MemberStatus
from events.models import EventRegistration, RegistrationStatus
from moderation.models import Report
from moderation.policies import IN_PROGRESS
from opportunities.models import (
    DistributionStatus,
    ModerationStatus,
    Opportunity,
    OpportunityCommunity,
    OpportunityStatus,
    OpportunityType,
)
from referrals.models import ReferralRequest, ReferralStatus

R = ReferralStatus
# Each referral step with the statuses that mean it was reached.
_REFERRAL_STEPS = (
    ("accepted", (R.ACCEPTED, R.REFERRED, R.APPLICATION_SUBMITTED, R.INTERVIEW, R.OFFER, R.JOINED)),
    ("referred", (R.REFERRED, R.APPLICATION_SUBMITTED, R.INTERVIEW, R.OFFER, R.JOINED)),
    ("joined", (R.JOINED,)),
)


@dataclass(frozen=True)
class Funnel:
    name: str
    # (step, how many reached it), in order.
    steps: tuple[tuple[str, int], ...]


def _reached(statuses: tuple[str, ...]) -> Count:
    """Rows that are in, or ever moved to, one of ``statuses``."""
    return Count(
        "pk",
        distinct=True,
        filter=Q(status__in=statuses) | Q(history__to_status__in=statuses),
    )


def _views(opportunities: QuerySet[Opportunity]) -> int:
    total: int | None = DailyOpportunityViews.objects.filter(
        opportunity__in=opportunities
    ).aggregate(total=Sum("views"))["total"]
    return total or 0


def applications(jobs: QuerySet[Opportunity]) -> Funnel:
    """Opened → applied → each stage of the pipeline → hired."""
    later = STAGES[1:]
    counted: dict[str, int] = Application.objects.filter(opportunity__in=jobs).aggregate(
        applied=Count("pk", distinct=True),
        **{stage.lower(): _reached(tuple(STAGES[STAGES.index(stage) :])) for stage in later},
    )
    steps = [("views", _views(jobs)), ("applied", counted["applied"])]
    steps += [(stage.lower(), counted[stage.lower()]) for stage in later]
    return Funnel("applications", tuple(steps))


def registrations(events: QuerySet[Opportunity]) -> Funnel:
    """Opened → registered → still holding a place → came."""
    counted: dict[str, int] = EventRegistration.objects.filter(
        event__in=events.values("pk")
    ).aggregate(
        registered=Count("pk"),
        going=Count("pk", filter=Q(status=RegistrationStatus.CONFIRMED)),
        attended=Count("pk", filter=Q(checked_in_at__isnull=False)),
    )
    return Funnel(
        "registrations",
        (
            ("views", _views(events)),
            ("registered", counted["registered"]),
            ("going", counted["going"]),
            ("attended", counted["attended"]),
        ),
    )


def referrals(jobs: QuerySet[Opportunity]) -> Funnel:
    """Asked for → accepted → referred → joined."""
    counted: dict[str, int] = ReferralRequest.objects.filter(opportunity__in=jobs).aggregate(
        requested=Count("pk", distinct=True),
        **{step: _reached(statuses) for step, statuses in _REFERRAL_STEPS},
    )
    return Funnel(
        "referrals",
        (
            ("requested", counted["requested"]),
            *((step, counted[step]) for step, _ in _REFERRAL_STEPS),
        ),
    )


def for_opportunities(opportunities: QuerySet[Opportunity]) -> list[Funnel]:
    """Every funnel that applies to the given opportunities. Jobs and events are counted
    apart, so that views of one never dilute the other."""
    jobs = opportunities.filter(type=OpportunityType.JOB)
    events = opportunities.filter(type=OpportunityType.EVENT)
    found = []
    if jobs.exists():
        found += [applications(jobs), referrals(jobs)]
    if events.exists():
        found.append(registrations(events))
    return found


def as_data(funnels: list[Funnel]) -> list[dict[str, Any]]:
    return [
        {
            "name": funnel.name,
            "steps": [{"key": key, "count": count} for key, count in funnel.steps],
        }
        for funnel in funnels
    ]


# --- A community -------------------------------------------------------------------------


def community_numbers(community: Community) -> dict[str, dict[str, int]]:
    """What a community's admins need to see how it is doing: its members, what it was
    offered and decided to show, and the reports waiting for its moderators.

    Nothing about applications or registrations: an opportunity is usually shown in several
    places, and nothing records which of them led someone to act.
    """
    S, D = MemberStatus, DistributionStatus
    shown = Q(
        status=D.APPROVED,
        opportunity__status=OpportunityStatus.PUBLISHED,
        opportunity__moderation_status=ModerationStatus.VISIBLE,
    )
    return {
        "members": CommunityMember.objects.filter(community=community).aggregate(
            active=Count("pk", filter=Q(status=S.ACTIVE)),
            asked_to_join=Count("pk", filter=Q(status=S.PENDING)),
            invited=Count("pk", filter=Q(status=S.INVITED)),
        ),
        "sharing": OpportunityCommunity.objects.filter(community=community).aggregate(
            offered=Count("pk"),
            waiting=Count("pk", filter=Q(status=D.PENDING)),
            declined=Count("pk", filter=Q(status=D.REJECTED)),
            removed=Count("pk", filter=Q(status=D.REMOVED)),
            shown=Count("pk", filter=shown),
            jobs_shown=Count("pk", filter=shown & Q(opportunity__type=OpportunityType.JOB)),
            events_shown=Count("pk", filter=shown & Q(opportunity__type=OpportunityType.EVENT)),
            featured=Count("pk", filter=shown & Q(is_featured=True)),
        ),
        "reports": Report.objects.filter(scope_community=community).aggregate(
            waiting=Count("pk", filter=Q(status__in=IN_PROGRESS)),
            decided=Count("pk", filter=~Q(status__in=IN_PROGRESS)),
        ),
    }
