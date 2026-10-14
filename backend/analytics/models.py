from django.db import models

from common.models import UUIDModel


class DailyOpportunityViews(UUIDModel):
    """How many different people opened an opportunity on one day.

    The only number here that cannot be worked out again from other tables: a view leaves
    no other trace. Who viewed is never stored.
    """

    opportunity = models.ForeignKey(
        "opportunities.Opportunity", on_delete=models.CASCADE, related_name="daily_views"
    )
    date = models.DateField()
    views = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "daily opportunity views"
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "date"], name="analytics_daily_views_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.opportunity_id} {self.date}: {self.views}"


class OpportunityStats(models.Model):
    """What has happened to an opportunity, counted. Derived: every number can be rebuilt
    from the tables it summarizes, and ``services.refresh`` does exactly that."""

    opportunity = models.OneToOneField(
        "opportunities.Opportunity",
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="stats",
    )
    views = models.PositiveIntegerField(default=0)
    # Within ``policies.RECENT``; what the popularity score uses.
    recent_views = models.PositiveIntegerField(default=0)
    saves = models.PositiveIntegerField(default=0)
    applications = models.PositiveIntegerField(default=0)
    registrations = models.PositiveIntegerField(default=0)
    referrals = models.PositiveIntegerField(default=0)
    popularity_score = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "opportunity stats"
        indexes = [
            # The "popular" order of the feed.
            models.Index(fields=["-popularity_score"], name="analytics_stats_popular"),
        ]

    def __str__(self) -> str:
        return f"{self.opportunity_id}: {self.popularity_score}"
