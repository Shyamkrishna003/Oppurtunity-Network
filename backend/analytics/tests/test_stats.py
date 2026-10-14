"""Counting views, rebuilding each opportunity's numbers, and the "popular" order."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from analytics import policies, services
from analytics.models import DailyOpportunityViews, OpportunityStats
from applications.tests.factories import make_application
from events.tests.factories import add_registration, make_event
from opportunities.models import SavedOpportunity
from opportunities.tests.factories import make_job
from organizations.tests.factories import organization_with_roles
from referrals.tests.factories import make_referral
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def page(job) -> str:
    return f"/api/v1/opportunities/{job.pk}/"


def numbers(job) -> str:
    return f"/api/v1/opportunities/{job.pk}/stats/"


def views_of(job) -> int:
    return sum(
        DailyOpportunityViews.objects.filter(opportunity=job).values_list("views", flat=True)
    )


def seen(job, views: int, days_ago: int = 0) -> None:
    DailyOpportunityViews.objects.create(
        opportunity=job, date=timezone.localdate() - timedelta(days=days_ago), views=views
    )


# --- Counting views ---------------------------------------------------------------------


def test_opening_an_opportunity_counts_once_per_person_and_day(api, api_as):
    job = make_job(status="PUBLISHED")
    ada, grace = UserFactory.create(), UserFactory.create()

    for _ in range(3):
        assert api_as(ada).get(page(job)).status_code == 200
    assert views_of(job) == 1

    api_as(grace).get(page(job))
    api.get(page(job))  # a visitor
    api.get(page(job))  # the same visitor again
    assert views_of(job) == 3
    row = DailyOpportunityViews.objects.get(opportunity=job)
    assert (row.date, row.views) == (timezone.localdate(), 3)


def test_views_by_the_people_who_run_it_do_not_count(api_as):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    job = make_job(status="PUBLISHED", organization=organization)

    api_as(members["RECRUITER"].user).get(page(job))
    api_as(members["OWNER"].user).get(page(job))
    for role in ("MODERATOR", "ADMIN"):
        api_as(UserFactory.create(platform_role=role)).get(page(job))
    assert views_of(job) == 0

    # A plain member of the organization does not manage its postings.
    api_as(members["MEMBER"].user).get(page(job))
    assert views_of(job) == 1


def test_only_reading_something_open_to_the_public_counts(api_as):
    owner = UserFactory.create()
    draft = make_job(status="DRAFT", creator=owner)
    closed = make_job(status="CLOSED")
    hidden = make_job(status="PUBLISHED", moderation_status="HIDDEN")
    reader = UserFactory.create()

    assert api_as(reader).get(page(draft)).status_code == 404
    assert api_as(reader).get(page(closed)).status_code == 200
    assert api_as(reader).get(page(hidden)).status_code == 404
    api_as(UserFactory.create(platform_role="MODERATOR")).get(page(hidden))

    assert DailyOpportunityViews.objects.count() == 0


def test_saving_or_editing_does_not_count_as_a_view(api_as):
    job = make_job(status="PUBLISHED")

    assert api_as(UserFactory.create()).put(f"{page(job)}save/").status_code == 204
    assert api_as(job.creator).patch(page(job), {"description": "New."}).status_code == 200

    assert views_of(job) == 0


def test_adding_a_view_never_fails_for_something_that_is_gone():
    job = make_job(status="PUBLISHED")
    today = timezone.localdate()

    services.add_view(job.pk, today)
    services.add_view(job.pk, today)
    services.add_view(uuid.uuid4(), today)  # deleted in the meantime: nothing to count

    assert views_of(job) == 2
    assert DailyOpportunityViews.objects.count() == 1


# --- Rebuilding the numbers -------------------------------------------------------------


@pytest.fixture
def busy():
    """A job and an event with a little of everything having happened to them."""
    job = make_job(status="PUBLISHED")
    seen(job, 10)
    seen(job, 7, days_ago=3)
    seen(job, 100, days_ago=45)  # too long ago to make it popular now
    for _ in range(2):
        SavedOpportunity.objects.create(user=UserFactory.create(), opportunity=job)
    make_application(opportunity=job)
    make_application(opportunity=job, status="WITHDRAWN")
    for status in ("REQUESTED", "REFERRED", "JOINED", "DECLINED"):
        make_referral(job, UserFactory.create(), UserFactory.create(), status=status)

    event = make_event(status="PUBLISHED")
    add_registration(event)
    add_registration(event)
    add_registration(event, status="WAITLISTED")
    add_registration(event, status="CANCELLED")
    return job, event


def test_the_numbers_are_rebuilt_from_what_happened(busy, django_assert_max_num_queries):
    job, event = busy
    untouched = make_job(status="PUBLISHED")
    draft = make_job(status="DRAFT")

    with django_assert_max_num_queries(4):
        assert services.refresh() == 3

    stats = OpportunityStats.objects.get(opportunity=job)
    assert (stats.views, stats.recent_views) == (117, 17)
    assert (stats.saves, stats.applications, stats.referrals) == (2, 2, 2)
    assert stats.registrations == 0
    assert stats.popularity_score == 17 + 3 * 2 + 5 * (2 + 2)

    of_event = OpportunityStats.objects.get(opportunity=event)
    assert of_event.registrations == 2
    assert of_event.popularity_score == 10
    assert OpportunityStats.objects.get(opportunity=untouched).popularity_score == 0
    assert not OpportunityStats.objects.filter(opportunity=draft).exists()


def test_rebuilding_twice_changes_nothing_and_follows_what_changes(busy):
    job, _ = busy
    services.refresh()
    before = OpportunityStats.objects.get(opportunity=job).popularity_score

    services.refresh()
    assert OpportunityStats.objects.get(opportunity=job).popularity_score == before
    assert OpportunityStats.objects.count() == 2

    SavedOpportunity.objects.filter(opportunity=job).delete()
    services.refresh()
    stats = OpportunityStats.objects.get(opportunity=job)
    assert (stats.saves, stats.popularity_score) == (0, before - 6)


def test_popularity_values_what_people_did_over_how_often_they_looked():
    looked_at = policies.popularity(
        recent_views=4, saves=0, applications=0, registrations=0, referrals=0
    )
    applied_to = policies.popularity(
        recent_views=0, saves=0, applications=1, registrations=0, referrals=0
    )

    assert applied_to > looked_at


# --- The popular order ------------------------------------------------------------------


def test_the_feed_can_be_ordered_by_popularity(api, django_assert_max_num_queries):
    now = timezone.now()
    quiet = make_job(status="PUBLISHED", published_at=now - timedelta(days=1))
    loved = make_job(status="PUBLISHED", published_at=now - timedelta(days=5))
    liked = make_job(status="PUBLISHED", published_at=now - timedelta(days=9))
    make_application(opportunity=loved)
    seen(liked, 3)
    services.refresh()
    # Published after the last rebuild: no numbers yet, so it counts as zero.
    fresh = make_job(status="PUBLISHED", published_at=now)

    with django_assert_max_num_queries(4):
        response = api.get("/api/v1/opportunities/", {"sort": "popular"})

    assert response.status_code == 200
    order = [row["id"] for row in response.json()["results"]]
    assert order == [str(o.pk) for o in (loved, liked, fresh, quiet)]


def test_popularity_never_shows_what_the_viewer_may_not_see(api):
    hidden = make_job(status="PUBLISHED", moderation_status="HIDDEN")
    seen(hidden, 500)
    shown = make_job(status="PUBLISHED")
    services.refresh()

    rows = api.get("/api/v1/opportunities/", {"sort": "popular"}).json()["results"]

    assert [row["id"] for row in rows] == [str(shown.pk)]
    assert api.get("/api/v1/opportunities/", {"sort": "loudest"}).status_code == 400


# --- What a manager is shown ------------------------------------------------------------


def test_an_opportunitys_numbers_are_for_the_people_who_manage_it(api, api_as):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    job = make_job(status="PUBLISHED", organization=organization)
    draft = make_job(status="DRAFT", organization=organization)

    assert api.get(numbers(job)).status_code == 401
    assert api_as(UserFactory.create()).get(numbers(job)).status_code == 403
    assert api_as(members["MEMBER"].user).get(numbers(job)).status_code == 403
    assert api_as(UserFactory.create(platform_role="ADMIN")).get(numbers(job)).status_code == 403
    assert api_as(UserFactory.create()).get(numbers(draft)).status_code == 404
    for role in ("OWNER", "RECRUITER"):
        assert api_as(members[role].user).get(numbers(job)).status_code == 200
        assert api_as(members[role].user).get(numbers(draft)).status_code == 200


def test_a_manager_sees_the_numbers_as_they_are_now(busy, api_as, django_assert_max_num_queries):
    job, _ = busy
    client = api_as(job.creator)

    with django_assert_max_num_queries(6):
        data = client.get(numbers(job)).json()

    # Counted live: nothing was rebuilt first.
    assert not OpportunityStats.objects.exists()
    by_day = data.pop("views_by_day")
    assert data == {
        "views": 117,
        "recent_views": 17,
        "saves": 2,
        "applications": 2,
        "registrations": 0,
        "referrals": 2,
        "popularity_score": 43,
    }
    assert len(by_day) == 14
    today = timezone.localdate()
    assert by_day[-1] == {"date": today.isoformat(), "views": 10}
    assert by_day[-4] == {"date": (today - timedelta(days=3)).isoformat(), "views": 7}
    assert sum(day["views"] for day in by_day) == 17
