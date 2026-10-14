"""Counting views and keeping each opportunity's numbers up to date."""

import hashlib
from collections.abc import Iterator
from datetime import date
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from analytics import policies, selectors, tasks
from analytics.models import DailyOpportunityViews, OpportunityStats
from common import request_context
from common.tasks import enqueue
from opportunities.models import Opportunity, OpportunityStatus
from users.models import User

_SEEN_SECONDS = 24 * 60 * 60
REFRESH_CHUNK = 500


def _seen_key(viewer: User | None, opportunity_id: UUID, day: date) -> str | None:
    """The cache key that remembers this viewer saw this opportunity today. A visitor is
    told apart by address, kept only as a keyed hash and only for a day. ``None`` when
    there is nothing to tell them apart by."""
    who = str(viewer.pk) if viewer is not None else request_context.get_client_ip()
    if not who:
        return None
    raw = f"{settings.SECRET_KEY}:{who}:{opportunity_id}:{day.isoformat()}"
    return f"analytics:seen:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def note_view(viewer: User | None, opportunity: Opportunity, *, manages: bool) -> bool:
    """Count that someone opened the opportunity, at most once per viewer and day. Returns
    whether it counted. Nothing is written here: a background task adds it to the total."""
    if not policies.counts_as_view(viewer, opportunity, manages=manages):
        return False
    day = timezone.localdate()
    key = _seen_key(viewer, opportunity.pk, day)
    # ``add`` only succeeds for the first caller, so two tabs opening at once count once.
    if key is None or not cache.add(key, 1, timeout=_SEEN_SECONDS):
        return False
    enqueue(tasks.record_view, str(opportunity.pk), day.isoformat())
    return True


def add_view(opportunity_id: UUID, day: date) -> None:
    """Add one view to the day's count. Safe to run concurrently; not safe to repeat, which
    is why the task that calls it never retries: a lost view is better than a double one."""
    today = DailyOpportunityViews.objects.filter(opportunity_id=opportunity_id, date=day)
    if today.update(views=F("views") + 1):
        return
    # Deleted since it was opened: nothing to count. Asked first, because the database only
    # checks that link when the transaction ends, too late to catch here.
    if not Opportunity.objects.filter(pk=opportunity_id).exists():
        return
    try:
        with transaction.atomic():
            DailyOpportunityViews.objects.create(opportunity_id=opportunity_id, date=day, views=1)
    except IntegrityError:
        # Another worker created the day's row first.
        today.update(views=F("views") + 1)


def _chunks(queryset: Iterator[UUID], size: int) -> Iterator[list[UUID]]:
    chunk: list[UUID] = []
    for pk in queryset:
        chunk.append(pk)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def refresh() -> int:
    """Rebuild the numbers of every published opportunity from the tables they summarize.
    Running it twice gives the same result. Returns how many were refreshed."""
    published = (
        Opportunity.objects.filter(status=OpportunityStatus.PUBLISHED)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    refreshed = 0
    now = timezone.now()
    for chunk in _chunks(published.iterator(chunk_size=REFRESH_CHUNK), REFRESH_CHUNK):
        rows = [
            OpportunityStats(
                opportunity_id=opportunity_id,
                **numbers,
                popularity_score=policies.popularity(
                    recent_views=numbers["recent_views"],
                    saves=numbers["saves"],
                    applications=numbers["applications"],
                    registrations=numbers["registrations"],
                    referrals=numbers["referrals"],
                ),
                updated_at=now,
            )
            for opportunity_id, numbers in selectors.numbers_for(chunk).items()
        ]
        OpportunityStats.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=["opportunity"],
            update_fields=[*selectors.NUMBERS, "popularity_score", "updated_at"],
        )
        refreshed += len(rows)
    return refreshed
