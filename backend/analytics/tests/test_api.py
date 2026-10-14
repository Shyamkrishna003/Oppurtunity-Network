from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from applications.tests.factories import make_application
from communities.tests.factories import CommunityFactory
from events.tests.factories import add_registration, make_event
from moderation.models import Report
from opportunities.models import Opportunity
from opportunities.tests.factories import make_job
from organizations.tests.factories import OrganizationFactory
from referrals.tests.factories import make_referral
from users.models import User
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

STATS = "/api/v1/admin/stats/"


def test_the_numbers_are_for_platform_admins_only(api, api_as):
    assert api.get(STATS).status_code == 401
    assert api_as(UserFactory.create()).get(STATS).status_code == 403
    assert api_as(UserFactory.create(platform_role="MODERATOR")).get(STATS).status_code == 403
    assert api_as(UserFactory.create(platform_role="ADMIN")).get(STATS).status_code == 200


def test_the_numbers_count_what_is_there(api_as, django_assert_max_num_queries):
    now = timezone.now()
    viewer = UserFactory.create(platform_role="ADMIN")
    UserFactory.create(email_verified_at=None)
    UserFactory.create(suspended_until=now + timedelta(days=3))
    UserFactory.create(suspended_until=now - timedelta(days=3))  # lapsed: not suspended now
    old = UserFactory.create()
    User.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=30))
    OrganizationFactory.create(verification_status="VERIFIED")
    OrganizationFactory.create()
    CommunityFactory.create()

    job = make_job(status="PUBLISHED", creator=viewer)
    make_job(status="PUBLISHED", creator=viewer, published_at=now - timedelta(days=40))
    make_job(status="DRAFT", creator=viewer)
    hidden = make_job(status="PUBLISHED", creator=viewer, moderation_status="HIDDEN")
    event = make_event(status="PUBLISHED", creator=viewer)

    make_application(opportunity=job, applicant=old)
    make_application(opportunity=job, status="HIRED")
    add_registration(event)
    came = add_registration(event)
    type(came).objects.filter(pk=came.pk).update(checked_in_at=now)
    add_registration(event, status="CANCELLED")
    for status in ("REQUESTED", "REFERRED", "JOINED"):
        make_referral(job, UserFactory.create(), UserFactory.create(), status=status)
    for status in ("OPEN", "OPEN", "UNDER_REVIEW", "DISMISSED"):
        Report.objects.create(
            reporter=UserFactory.create(),
            target_type="OPPORTUNITY",
            target_opportunity=hidden,
            category="SPAM",
            status=status,
        )
    cache.clear()

    # One query to know the caller, then one per table counted.
    with django_assert_max_num_queries(10):
        data = api_as(viewer).get(STATS).json()

    total = User.objects.count()
    assert data["users"] == {
        "total": total,
        "verified": total - 1,
        "joined_recently": total - 1,
        "suspended": 1,
    }
    assert data["organizations"] == {"total": 2, "verified": 1}
    assert data["communities"] == {"total": 1}
    assert data["opportunities"] == {
        "published": 3,
        "jobs": 2,
        "events": 1,
        "published_recently": Opportunity.objects.filter(
            published_at__gte=now - timedelta(days=7)
        ).count(),
        "hidden_or_removed": 1,
    }
    assert data["opportunities"]["published_recently"] == 3
    assert data["outcomes"] == {
        "applications": 2,
        "hires": 1,
        "registrations": 2,
        "attendances": 1,
        "referrals": 2,
        "referral_joins": 1,
    }
    assert data["reports"] == {"waiting": 2, "under_review": 1}


def test_the_numbers_are_kept_for_a_minute(api_as, django_assert_max_num_queries):
    client = api_as(UserFactory.create(platform_role="ADMIN"))
    first = client.get(STATS).json()
    UserFactory.create()

    with django_assert_max_num_queries(1):  # only to know the caller
        again = client.get(STATS).json()

    assert again == first
    cache.clear()
    assert client.get(STATS).json()["users"]["total"] == first["users"]["total"] + 1
