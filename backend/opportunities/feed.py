"""The opportunity feed: search, filters and ordering, all in SQL.

Everything starts from ``selectors.visible_to``, so a filter can narrow what a viewer sees
but never widen it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramSimilarity
from django.db.models import Exists, F, OuterRef, QuerySet, Value
from django.db.models.fields import BooleanField
from django.utils import timezone

from communities.models import CommunityMember, MemberStatus
from communities.selectors import visible_to as visible_communities
from opportunities import selectors
from opportunities.models import (
    DistributionStatus,
    ModerationStatus,
    Opportunity,
    OpportunityCommunity,
    OpportunitySkill,
    OpportunityStatus,
    SavedOpportunity,
)
from opportunities.relevance import Matcher, score_expression
from users.models import User

SEARCH_CONFIG = "english"
# Without a search term, "most relevant" ranks recent opportunities only: an old posting
# that happens to match well should not sit above this week's.
RELEVANCE_WINDOW = timedelta(days=90)
# How close a title must be to the search term to count as a near miss (0 to 1).
TITLE_SIMILARITY = 0.3

NEWEST, DEADLINE, RELEVANT = "newest", "deadline", "relevant"
SORTS = (NEWEST, DEADLINE, RELEVANT)
SCOPES = ("all", "communities")


@dataclass(frozen=True)
class FeedQuery:
    """A validated request for the feed. Field names match the URL parameters."""

    q: str = ""
    type: str = ""
    skill: list[UUID] = field(default_factory=list)
    country: str = ""
    city: str = ""
    work_mode: str = ""
    experience_level: str = ""
    employment_type: str = ""
    community: UUID | None = None
    organization: UUID | None = None
    deadline_before: datetime | None = None
    deadline_after: datetime | None = None
    posted_within: int | None = None  # days
    saved: bool = False
    scope: str = "all"
    sort: str = ""

    @property
    def effective_sort(self) -> str:
        """A search is ordered by how well it matches unless told otherwise; browsing is
        ordered by date."""
        return self.sort or (RELEVANT if self.q else NEWEST)


def _open_and_visible(viewer: User | AnonymousUser) -> QuerySet[Opportunity]:
    # visible_to also lets managers see their own drafts and closed postings; the feed is
    # for what can be acted on now.
    return selectors.visible_to(viewer).filter(
        status=OpportunityStatus.PUBLISHED, moderation_status=ModerationStatus.VISIBLE
    )


def _approved_in(communities: Any) -> Exists:
    return Exists(
        OpportunityCommunity.objects.filter(
            opportunity=OuterRef("pk"),
            status=DistributionStatus.APPROVED,
            community__in=communities,
        )
    )


def _apply_filters(
    opportunities: QuerySet[Opportunity], query: FeedQuery, viewer: User | AnonymousUser
) -> QuerySet[Opportunity]:
    exact = {
        "type": query.type,
        "work_mode": query.work_mode,
        "country_code": query.country.upper(),
        "city__iexact": query.city.strip(),
        "job__experience_level": query.experience_level,
        "job__employment_type": query.employment_type,
        "organization_id": query.organization,
        "deadline__lte": query.deadline_before,
        "deadline__gte": query.deadline_after,
    }
    opportunities = opportunities.filter(**{k: v for k, v in exact.items() if v})

    if query.skill:
        # Any of the chosen skills.
        opportunities = opportunities.filter(
            Exists(
                OpportunitySkill.objects.filter(
                    opportunity=OuterRef("pk"), skill_id__in=query.skill
                )
            )
        )
    if query.community:
        # Only a community the viewer can see: the filter must not confirm what a private
        # community shows.
        visible = visible_communities(viewer).filter(pk=query.community).values("pk")
        opportunities = opportunities.filter(_approved_in(visible))
    if query.posted_within:
        since = timezone.now() - timedelta(days=query.posted_within)
        opportunities = opportunities.filter(published_at__gte=since)

    # The two filters below are about the viewer; for a visitor they match nothing.
    if query.scope == "communities":
        mine = (
            CommunityMember.objects.filter(user=viewer, status=MemberStatus.ACTIVE).values(
                "community"
            )
            if viewer.is_authenticated
            else []
        )
        opportunities = opportunities.filter(_approved_in(mine))
    if query.saved:
        if not viewer.is_authenticated:
            return opportunities.none()
        opportunities = opportunities.filter(
            Exists(SavedOpportunity.objects.filter(opportunity=OuterRef("pk"), user=viewer))
        )
    return opportunities


def _search(opportunities: QuerySet[Opportunity], term: str) -> QuerySet[Opportunity]:
    """Annotate ``text_rank`` and keep what matches ``term``.

    Full-text search first (it understands word forms, quoted phrases and ``-exclusions``).
    If that finds nothing, fall back to titles that are merely close to the term, so a typo
    still leads somewhere.
    """
    parsed = SearchQuery(term, search_type="websearch", config=SEARCH_CONFIG)
    matching = opportunities.filter(search_vector=parsed)
    if matching.exists():
        return matching.annotate(
            text_rank=SearchRank(F("search_vector"), parsed, cover_density=True)
        )
    return opportunities.annotate(text_rank=TrigramSimilarity("title", term)).filter(
        text_rank__gte=TITLE_SIMILARITY
    )


def build_feed(
    viewer: User | AnonymousUser, query: FeedQuery, matcher: Matcher | None
) -> QuerySet[Opportunity]:
    """The feed for ``viewer``, filtered and ordered as ``query`` asks.

    ``matcher`` carries the viewer's profile for relevance; pass ``None`` for a visitor.
    Every row is annotated with ``is_saved``.
    """
    opportunities = _apply_filters(_open_and_visible(viewer), query, viewer)
    if query.q:
        opportunities = _search(opportunities, query.q)

    sort = query.effective_sort
    if sort == RELEVANT:
        score = score_expression(matcher) if matcher is not None else Value(0)
        opportunities = opportunities.annotate(relevance=score)
        if query.q:
            order = ["-text_rank", "-relevance", "-published_at", "-id"]
        else:
            opportunities = opportunities.filter(
                published_at__gte=timezone.now() - RELEVANCE_WINDOW
            )
            order = ["-relevance", "-published_at", "-id"]
        opportunities = opportunities.order_by(*order)
    elif sort == DEADLINE:
        # Soonest deadline first; opportunities with no deadline come last.
        opportunities = opportunities.order_by(F("deadline").asc(nulls_last=True), "-id")
    else:
        opportunities = opportunities.order_by("-published_at", "-id")

    saved = (
        Exists(SavedOpportunity.objects.filter(opportunity=OuterRef("pk"), user=viewer))
        if viewer.is_authenticated
        else Value(False, output_field=BooleanField())
    )
    return selectors.with_details(opportunities.annotate(is_saved=saved))
