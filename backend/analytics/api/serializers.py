from typing import Any

from rest_framework import serializers


class _Counts(serializers.Serializer[Any]):
    """A group of whole numbers. Subclasses name them."""


class UserCountsSerializer(_Counts):
    total = serializers.IntegerField()
    verified = serializers.IntegerField()
    # In the last seven days.
    joined_recently = serializers.IntegerField()
    suspended = serializers.IntegerField()


class OrganizationCountsSerializer(_Counts):
    total = serializers.IntegerField()
    verified = serializers.IntegerField()


class CommunityCountsSerializer(_Counts):
    total = serializers.IntegerField()


class OpportunityCountsSerializer(_Counts):
    # Published and not hidden: what people can find now.
    published = serializers.IntegerField()
    jobs = serializers.IntegerField()
    events = serializers.IntegerField()
    # In the last seven days.
    published_recently = serializers.IntegerField()
    hidden_or_removed = serializers.IntegerField()


class OutcomeCountsSerializer(_Counts):
    applications = serializers.IntegerField()
    hires = serializers.IntegerField()
    # Places held at events now, and people who actually came.
    registrations = serializers.IntegerField()
    attendances = serializers.IntegerField()
    # Referrals a referrer put their name to, and those that ended in someone joining.
    referrals = serializers.IntegerField()
    referral_joins = serializers.IntegerField()


class ReportCountsSerializer(_Counts):
    waiting = serializers.IntegerField()
    under_review = serializers.IntegerField()


class DayViewsSerializer(serializers.Serializer[Any]):
    date = serializers.DateField()
    views = serializers.IntegerField()


class OpportunityNumbersSerializer(_Counts):
    """How one opportunity is doing, for the people who manage it."""

    # Different people who opened it, counted once a day each. Not its managers.
    views = serializers.IntegerField()
    # In the last thirty days.
    recent_views = serializers.IntegerField()
    saves = serializers.IntegerField()
    applications = serializers.IntegerField()
    # Places held at the event now.
    registrations = serializers.IntegerField()
    # Referrals a referrer put their name to.
    referrals = serializers.IntegerField()
    # What the "popular" order of the feed goes by.
    popularity_score = serializers.IntegerField()
    # The last fourteen days, oldest first.
    views_by_day = DayViewsSerializer(many=True)


class PlatformTotalsSerializer(serializers.Serializer[Any]):
    # The numbers are kept for up to a minute; this is when they were counted.
    generated_at = serializers.DateTimeField()
    users = UserCountsSerializer()
    organizations = OrganizationCountsSerializer()
    communities = CommunityCountsSerializer()
    opportunities = OpportunityCountsSerializer()
    outcomes = OutcomeCountsSerializer()
    reports = ReportCountsSerializer()
