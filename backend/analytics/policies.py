"""Rules for counting: whose views count, and how popularity is scored. Pure functions."""

from datetime import timedelta

from opportunities.models import ModerationStatus, Opportunity, OpportunityStatus
from users.models import User
from users.policies import is_platform_staff

# Views older than this no longer make something popular.
RECENT = timedelta(days=30)

# Popularity rewards what people did, not how often they looked: one application is worth
# five views. Fixed weights, so any ranking can be explained from the numbers shown.
VIEW_WEIGHT = 1
SAVE_WEIGHT = 3
ACTION_WEIGHT = 5


def popularity(
    *, recent_views: int, saves: int, applications: int, registrations: int, referrals: int
) -> int:
    return (
        VIEW_WEIGHT * recent_views
        + SAVE_WEIGHT * saves
        + ACTION_WEIGHT * (applications + registrations + referrals)
    )


def counts_as_view(viewer: User | None, opportunity: Opportunity, *, manages: bool) -> bool:
    """Whether this person opening the opportunity is a view worth counting. Only of
    something the public can act on, and not by the people who run it or the platform:
    their visits say nothing about interest."""
    if (
        opportunity.status != OpportunityStatus.PUBLISHED
        or opportunity.moderation_status != ModerationStatus.VISIBLE
    ):
        return False
    if viewer is None:
        return True
    return not manages and not is_platform_staff(viewer)
