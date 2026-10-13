"""Read queries for referrals. Views load objects only through these."""

from uuid import UUID

from django.db.models import Q, QuerySet
from django.http import Http404
from django.utils import timezone

from applications import selectors as applications
from applications.models import Application
from connections.selectors import connections_of
from opportunities import selectors as opportunities
from opportunities.models import Opportunity
from opportunities.selectors import Viewer
from organizations.models import MembershipStatus, OrganizationMember
from referrals import policies
from referrals.models import ReferralRequest, ReferralStatusHistory
from referrals.policies import OPEN, Actor, Barrier
from users.models import User, UserBlock

# Someone with more eligible connections than this at one organization picks from the
# first ones by name; the list is a chooser, not a directory.
MAX_ELIGIBLE_LISTED = 50


def visible_to(user: User) -> QuerySet[ReferralRequest]:
    """Referrals the user may see: those they asked for, those asked of them, and those
    already made for jobs they manage. Nobody else can, platform staff included."""
    managed = Opportunity.objects.filter(opportunities.managed_by(user))
    return ReferralRequest.objects.filter(
        Q(requester=user) | Q(referrer=user) | Q(referred_at__isnull=False, opportunity__in=managed)
    )


def _with_details(queryset: QuerySet[ReferralRequest]) -> QuerySet[ReferralRequest]:
    return queryset.select_related(
        "opportunity__organization", "requester__profile", "referrer__profile"
    )


def actor_for(user: User, referral: ReferralRequest) -> Actor:
    is_party = user.pk in (referral.requester_id, referral.referrer_id)
    return Actor(
        is_requester=referral.requester_id == user.pk,
        is_referrer=referral.referrer_id == user.pk,
        # Only looked up for someone who is neither of the two people.
        is_manager=not is_party and applications.is_manager(user, referral.opportunity),
    )


def get_referral(user: User, referral_id: UUID) -> ReferralRequest:
    """The referral if the user may see it, else 404: someone else's referral and one that
    does not exist look the same."""
    referral = _with_details(visible_to(user).filter(pk=referral_id)).first()
    if referral is None:
        raise Http404
    return referral


def list_for(
    user: User, *, as_referrer: bool, status: str = "", opportunity_id: UUID | None = None
) -> QuerySet[ReferralRequest]:
    """What the user asked for, or what was asked of them, newest first."""
    referrals = ReferralRequest.objects.filter(
        Q(referrer=user) if as_referrer else Q(requester=user)
    )
    if status:
        referrals = referrals.filter(status=status)
    if opportunity_id is not None:
        referrals = referrals.filter(opportunity_id=opportunity_id)
    return _with_details(referrals)


def history_of(referral: ReferralRequest) -> QuerySet[ReferralStatusHistory]:
    return referral.history.order_by("created_at", "id")


def get_job(user: User, opportunity_id: UUID) -> Opportunity:
    """The opportunity, for someone about to ask for a referral to it. 404 if they cannot
    see it."""
    return opportunities.get_opportunity(user, opportunity_id)


def barrier_to_requesting(user: User, opportunity: Opportunity) -> Barrier | None:
    """What stops the user asking for a referral to this job (which they can see)."""
    application_status = (
        Application.objects.filter(opportunity=opportunity, applicant=user)
        .values_list("status", flat=True)
        .first()
    )
    return policies.barrier_to_requesting(
        opportunity,
        is_manager=applications.is_manager(user, opportunity),
        application_status=application_status,
        now=timezone.now(),
    )


def can_request(viewer: Viewer, opportunity: Opportunity) -> bool:
    """Whether to offer the viewer "ask for a referral" on this opportunity's page. It says
    nothing about whether they know anyone there: that is only looked up when they ask."""
    return viewer.is_authenticated and barrier_to_requesting(viewer, opportunity) is None


def _eligible(user: User, opportunity: Opportunity) -> QuerySet[User]:
    """Who the user may ask to refer them for this job: their own connections who are
    openly members of the organization and take referral requests.

    Starts from the user's connections, so it can only ever return people the user already
    knows; it reveals which of them work there only if they show that membership publicly.
    """
    members = OrganizationMember.objects.filter(
        organization__opportunities=opportunity,
        status=MembershipStatus.ACTIVE,
        is_public=True,
    ).values("user")
    return (
        connections_of(user)
        .filter(is_active=True, profile__accepts_referral_requests=True, pk__in=members)
        .exclude(pk=user.pk)
        # A block ends the connection, so this cannot match; it keeps the rule in one place.
        .exclude(pk__in=UserBlock.objects.filter(blocker=user).values("blocked"))
        .exclude(pk__in=UserBlock.objects.filter(blocked=user).values("blocker"))
    )


def eligible_referrers(user: User, opportunity: Opportunity) -> list[User]:
    """The people the user could still ask for this job, by name."""
    asked = ReferralRequest.objects.filter(opportunity=opportunity, requester=user).values(
        "referrer"
    )
    return list(
        _eligible(user, opportunity)
        .exclude(pk__in=asked)
        .select_related("profile")
        .order_by("profile__display_name", "pk")[:MAX_ELIGIBLE_LISTED]
    )


def get_eligible_referrer(user: User, opportunity: Opportunity, referrer_id: UUID) -> User | None:
    return _eligible(user, opportunity).select_related("profile").filter(pk=referrer_id).first()


def open_count(user: User, opportunity: Opportunity) -> int:
    return ReferralRequest.objects.filter(
        opportunity=opportunity, requester=user, status__in=OPEN
    ).count()


def is_active_member(user: User, opportunity: Opportunity) -> bool:
    return OrganizationMember.objects.filter(
        organization__opportunities=opportunity, user=user, status=MembershipStatus.ACTIVE
    ).exists()
