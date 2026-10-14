"""Funnels for an opportunity and an organization, and a community's numbers."""

import uuid

import pytest
from django.utils import timezone

from analytics import services
from analytics.models import DailyOpportunityViews
from applications.models import ApplicationStatusHistory
from applications.tests.factories import make_application
from communities.tests.factories import CommunityMemberFactory, community_with_roles
from events.tests.factories import add_registration, make_event
from moderation.models import Report
from opportunities.tests.factories import distribute, make_job
from organizations.tests.factories import organization_with_roles
from referrals.models import ReferralStatusHistory
from referrals.tests.factories import make_referral
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def seen(opportunity, views: int) -> None:
    DailyOpportunityViews.objects.create(
        opportunity=opportunity, date=timezone.localdate(), views=views
    )


def steps(data, name) -> dict[str, int]:
    (funnel,) = [funnel for funnel in data["funnels"] if funnel["name"] == name]
    return {step["key"]: step["count"] for step in funnel["steps"]}


def moved(application, *path) -> None:
    """Record that the application went through ``path`` before where it is now."""
    for source, target in zip(path, path[1:], strict=False):
        ApplicationStatusHistory.objects.create(
            application=application, from_status=source, to_status=target
        )


def fill(job) -> None:
    """Five applicants who got different distances, and four referral requests."""
    seen(job, 40)
    make_application(opportunity=job)
    make_application(opportunity=job, status="WITHDRAWN")
    make_application(opportunity=job, status="SHORTLISTED")
    # Skipped screening and shortlisting on the way: still got at least that far.
    make_application(opportunity=job, status="HIRED")
    # Interviewed, then turned down: reached the interview all the same.
    rejected = make_application(opportunity=job, status="REJECTED")
    moved(rejected, "APPLIED", "SCREENING", "INTERVIEW")

    for status in ("REQUESTED", "DECLINED", "ACCEPTED", "REFERRED", "JOINED"):
        make_referral(job, UserFactory.create(), UserFactory.create(), status=status)
    # Accepted, then the job closed: reached "accepted" all the same.
    closed = make_referral(job, UserFactory.create(), UserFactory.create(), status="CLOSED")
    ReferralStatusHistory.objects.create(
        referral=closed, from_status="REQUESTED", to_status="ACCEPTED"
    )


def numbers(opportunity) -> str:
    return f"/api/v1/opportunities/{opportunity.pk}/stats/"


# --- One opportunity ----------------------------------------------------------------------


def test_a_jobs_funnels_count_everyone_who_reached_each_step(api_as):
    job = make_job(status="PUBLISHED")
    fill(job)

    data = api_as(job.creator).get(numbers(job)).json()

    assert [funnel["name"] for funnel in data["funnels"]] == ["applications", "referrals"]
    assert steps(data, "applications") == {
        "views": 40,
        "applied": 5,
        "screening": 3,
        "shortlisted": 3,
        "interview": 2,
        "offer": 1,
        "hired": 1,
    }
    assert steps(data, "referrals") == {"requested": 6, "accepted": 4, "referred": 2, "joined": 1}


def test_an_events_funnel_follows_registration_to_the_door(api_as):
    event = make_event(status="PUBLISHED")
    seen(event, 25)
    for _ in range(2):
        add_registration(event)
    came = add_registration(event)
    type(came).objects.filter(pk=came.pk).update(checked_in_at=timezone.now())
    add_registration(event, status="WAITLISTED")
    add_registration(event, status="CANCELLED")

    data = api_as(event.creator).get(numbers(event)).json()

    assert [funnel["name"] for funnel in data["funnels"]] == ["registrations"]
    assert steps(data, "registrations") == {
        "views": 25,
        "registered": 5,
        "going": 3,
        "attended": 1,
    }


def test_a_funnel_with_nothing_in_it_is_all_zeros(api_as):
    job = make_job(status="PUBLISHED")

    data = api_as(job.creator).get(numbers(job)).json()

    assert set(steps(data, "applications").values()) == {0}
    assert set(steps(data, "referrals").values()) == {0}


# --- An organization ----------------------------------------------------------------------


def org_numbers(organization) -> str:
    return f"/api/v1/organizations/{organization.pk}/stats/"


def test_an_organizations_numbers_are_for_the_people_who_post_for_it(api, api_as):
    organization, members = organization_with_roles("ADMIN", "RECRUITER", "MEMBER")
    url = org_numbers(organization)

    assert api.get(url).status_code == 401
    assert api_as(members["MEMBER"].user).get(url).status_code == 403
    assert api_as(UserFactory.create()).get(url).status_code == 403
    assert api_as(UserFactory.create(platform_role="ADMIN")).get(url).status_code == 403
    for role in ("OWNER", "ADMIN", "RECRUITER"):
        assert api_as(members[role].user).get(url).status_code == 200
    unknown = f"/api/v1/organizations/{uuid.uuid4()}/stats/"
    assert api_as(members["OWNER"].user).get(unknown).status_code == 404


def test_an_organizations_numbers_add_up_its_own_postings_only(
    api_as, django_assert_max_num_queries
):
    organization, members = organization_with_roles()
    first = make_job(status="PUBLISHED", organization=organization, title="First")
    fill(first)
    second = make_job(status="PUBLISHED", organization=organization, title="Second")
    seen(second, 10)
    make_application(opportunity=second)
    event = make_event(status="PUBLISHED", organization=organization, title="Meetup")
    seen(event, 7)
    add_registration(event)
    make_job(status="DRAFT", organization=organization)
    make_job(status="CLOSED", organization=organization)
    hidden = make_job(status="PUBLISHED", organization=organization, moderation_status="HIDDEN")
    seen(hidden, 900)
    # Someone else's: never counted here.
    other, _ = organization_with_roles()
    fill(make_job(status="PUBLISHED", organization=other))
    fill(make_job(status="PUBLISHED"))
    services.refresh()

    with django_assert_max_num_queries(14):
        data = api_as(members["OWNER"].user).get(org_numbers(organization)).json()

    assert data["opportunities"] == {"drafts": 1, "published": 4, "finished": 1}
    assert [funnel["name"] for funnel in data["funnels"]] == [
        "applications",
        "referrals",
        "registrations",
    ]
    applications = steps(data, "applications")
    # Views of its jobs only: the event's are in the event funnel.
    assert (applications["views"], applications["applied"], applications["hired"]) == (950, 6, 1)
    assert steps(data, "referrals")["requested"] == 6
    assert steps(data, "registrations") == {"views": 7, "registered": 1, "going": 1, "attended": 0}
    # The most popular open ones first; a hidden one is not "top" however much it was seen.
    assert [row["title"] for row in data["top"]] == ["First", "Second", "Meetup"]
    assert data["top"][0] == {
        "id": str(first.pk),
        "title": "First",
        "type": "JOB",
        "views": 40,
        "applications": 5,
        "registrations": 0,
    }


def test_an_organization_that_posted_nothing_has_no_funnels(api_as):
    organization, members = organization_with_roles()

    data = api_as(members["OWNER"].user).get(org_numbers(organization)).json()

    assert data == {
        "opportunities": {"drafts": 0, "published": 0, "finished": 0},
        "funnels": [],
        "top": [],
    }


# --- A community --------------------------------------------------------------------------


def community_numbers(community) -> str:
    return f"/api/v1/communities/{community.pk}/stats/"


def test_a_communitys_numbers_are_for_its_owners_and_admins(api, api_as):
    community, members = community_with_roles("ADMIN", "MODERATOR", "MEMBER")
    url = community_numbers(community)

    assert api.get(url).status_code == 401
    for role in ("MODERATOR", "MEMBER"):
        assert api_as(members[role].user).get(url).status_code == 403
    assert api_as(UserFactory.create()).get(url).status_code == 403
    assert api_as(UserFactory.create(platform_role="ADMIN")).get(url).status_code == 403
    for role in ("OWNER", "ADMIN"):
        assert api_as(members[role].user).get(url).status_code == 200

    private, _ = community_with_roles(visibility="PRIVATE")
    assert api_as(UserFactory.create()).get(community_numbers(private)).status_code == 404


def test_a_communitys_numbers_count_members_sharing_and_reports(
    api_as, django_assert_max_num_queries
):
    community, members = community_with_roles("ADMIN")
    CommunityMemberFactory.create(community=community)
    for status in ("PENDING", "PENDING", "INVITED", "LEFT", "BANNED"):
        CommunityMemberFactory.create(community=community, status=status)

    job = make_job(status="PUBLISHED")
    distribute(job, community, is_featured=True)
    distribute(make_event(status="PUBLISHED"), community)
    # Approved, but no longer something members can find.
    distribute(make_job(status="CLOSED"), community)
    distribute(make_job(status="PUBLISHED", moderation_status="HIDDEN"), community)
    for status in ("PENDING", "REJECTED", "REMOVED"):
        distribute(make_job(status="PUBLISHED"), community, status=status)

    for status in ("OPEN", "UNDER_REVIEW", "DISMISSED"):
        Report.objects.create(
            reporter=UserFactory.create(),
            target_type="OPPORTUNITY",
            target_opportunity=job,
            category="SPAM",
            status=status,
            scope_community=community,
        )
    # The platform's report, and another community's business: not counted here.
    Report.objects.create(
        reporter=UserFactory.create(), target_type="OPPORTUNITY", target_opportunity=job,
        category="SPAM",
    )  # fmt: skip
    other, _ = community_with_roles()
    distribute(job, other)

    with django_assert_max_num_queries(8):
        data = api_as(members["ADMIN"].user).get(community_numbers(community)).json()

    assert data == {
        "members": {"active": 3, "asked_to_join": 2, "invited": 1},
        "sharing": {
            "offered": 7,
            "waiting": 1,
            "declined": 1,
            "removed": 1,
            "shown": 2,
            "jobs_shown": 1,
            "events_shown": 1,
            "featured": 1,
        },
        "reports": {"waiting": 2, "decided": 1},
    }
