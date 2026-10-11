"""Deterministic relevance: how well an opportunity fits what a user has told us.

No learned signals and no hidden state. The score is a fixed sum over facts the user entered
themselves (skills, interests, location, work mode) and communities they joined, and every
point of it can be shown back to them as a reason.

The calculation exists twice on purpose: as a SQL expression, so the database can order
thousands of rows by it, and in Python, so the reasons can be listed for the page being
shown. ``test_relevance`` asserts that the two always produce the same score.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import (
    Case,
    Count,
    Exists,
    Expression,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Least

from common.choices import WorkMode
from communities.models import CommunityMember, MemberStatus
from opportunities.models import (
    DistributionStatus,
    Opportunity,
    OpportunityCommunity,
    OpportunitySkill,
)
from users.models import SkillKind, User, UserSkill

SKILL_WEIGHT = 5
INTEREST_WEIGHT = 3
COMMUNITY_WEIGHT = 3
LOCATION_WEIGHT = 2
WORK_MODE_WEIGHT = 2
# At most this many matching skills (and as many interests) count, so an opportunity cannot
# climb the ranking just by listing every skill there is.
MATCH_CAP = 4


@dataclass(frozen=True)
class Matcher:
    """What the viewer has told us, loaded once per request."""

    has: dict[UUID, str]  # skill ID -> name
    interested: dict[UUID, str]
    community_ids: frozenset[UUID]
    city: str
    country_code: str
    work_mode: str

    @property
    def has_anything(self) -> bool:
        return bool(
            self.has or self.interested or self.community_ids or self.city or self.country_code
        ) or bool(self.work_mode)


@dataclass(frozen=True)
class Match:
    score: int
    # Each reason is {"kind": ..., "label": ...}; kinds: skill, interest, community,
    # location, work_mode.
    reasons: list[dict[str, str]]


def load_matcher(user: User) -> Matcher:
    skills: dict[str, dict[UUID, str]] = {kind: {} for kind in SkillKind.values}
    for kind, skill_id, name in UserSkill.objects.filter(user=user).values_list(
        "kind", "skill_id", "skill__name"
    ):
        skills[kind][skill_id] = name
    profile = user.profile
    return Matcher(
        has=skills[SkillKind.HAS],
        interested=skills[SkillKind.INTERESTED],
        community_ids=frozenset(
            CommunityMember.objects.filter(user=user, status=MemberStatus.ACTIVE).values_list(
                "community_id", flat=True
            )
        ),
        city=profile.city.strip(),
        country_code=profile.country_code,
        work_mode=profile.work_mode_preference,
    )


# --- In SQL -----------------------------------------------------------------------------


def _matching_skills(skill_ids: Any) -> Expression:
    """How many of the opportunity's skills are among ``skill_ids``, capped."""
    if not skill_ids:
        return Value(0)
    matches = (
        OpportunitySkill.objects.filter(opportunity=OuterRef("pk"), skill_id__in=skill_ids)
        .order_by()
        .values("opportunity")
        .annotate(matches=Count("pk"))
        .values("matches")
    )
    return Least(Coalesce(Subquery(matches, output_field=IntegerField()), 0), MATCH_CAP)


def _points(condition: Any, weight: int) -> Expression:
    if condition is None:
        return Value(0)
    return Case(When(condition, then=Value(weight)), default=Value(0), output_field=IntegerField())


def _location_condition(matcher: Matcher) -> Q | None:
    """Same city; or, for someone who gave only a country, the same country."""
    if matcher.city:
        return Q(city__iexact=matcher.city)
    if matcher.country_code:
        return Q(country_code=matcher.country_code)
    return None


def score_expression(matcher: Matcher) -> Expression:
    """The relevance score as a SQL expression, for annotating an ``Opportunity`` queryset.

    The viewer's own data goes in as literals; nothing is joined per row but the
    opportunity's skills and its community shares.
    """
    in_my_community = (
        Exists(
            OpportunityCommunity.objects.filter(
                opportunity=OuterRef("pk"),
                status=DistributionStatus.APPROVED,
                community_id__in=matcher.community_ids,
            )
        )
        if matcher.community_ids
        else None
    )
    work_mode = Q(work_mode=matcher.work_mode) if matcher.work_mode else None
    return (
        SKILL_WEIGHT * _matching_skills(list(matcher.has))
        + INTEREST_WEIGHT * _matching_skills(list(matcher.interested))
        + _points(in_my_community, COMMUNITY_WEIGHT)
        + _points(_location_condition(matcher), LOCATION_WEIGHT)
        + _points(work_mode, WORK_MODE_WEIGHT)
    )


# --- In Python --------------------------------------------------------------------------


def explain(matcher: Matcher, opportunity: Opportunity, community_names: list[str]) -> Match:
    """The same score, with the reasons behind it.

    ``opportunity.skills`` should be prefetched. ``community_names`` are the viewer's own
    communities that show this opportunity.
    """
    skill_ids = [skill.pk for skill in opportunity.skills.all()]
    owned = [matcher.has[pk] for pk in skill_ids if pk in matcher.has]
    wanted = [matcher.interested[pk] for pk in skill_ids if pk in matcher.interested]
    reasons = [
        *({"kind": "skill", "label": name} for name in sorted(owned)),
        *({"kind": "interest", "label": name} for name in sorted(wanted)),
        *({"kind": "community", "label": name} for name in sorted(community_names)),
    ]
    score = (
        SKILL_WEIGHT * min(len(owned), MATCH_CAP)
        + INTEREST_WEIGHT * min(len(wanted), MATCH_CAP)
        + (COMMUNITY_WEIGHT if community_names else 0)
    )

    if matcher.city:
        same_place = opportunity.city.lower() == matcher.city.lower()
        place = opportunity.city
    else:
        same_place = bool(matcher.country_code) and opportunity.country_code == matcher.country_code
        place = opportunity.country_code
    if same_place:
        score += LOCATION_WEIGHT
        reasons.append({"kind": "location", "label": place})

    if matcher.work_mode and opportunity.work_mode == matcher.work_mode:
        score += WORK_MODE_WEIGHT
        reasons.append({"kind": "work_mode", "label": str(WorkMode(matcher.work_mode).label)})

    return Match(score=score, reasons=reasons)


def community_names_by_opportunity(
    matcher: Matcher, opportunity_ids: list[UUID]
) -> dict[UUID, list[str]]:
    """For a page of results: which of the viewer's communities show each one. One query."""
    names: dict[UUID, list[str]] = {}
    if not matcher.community_ids or not opportunity_ids:
        return names
    rows = OpportunityCommunity.objects.filter(
        opportunity_id__in=opportunity_ids,
        community_id__in=matcher.community_ids,
        status=DistributionStatus.APPROVED,
    ).values_list("opportunity_id", "community__name")
    for opportunity_id, name in rows:
        names.setdefault(opportunity_id, []).append(name)
    return names
