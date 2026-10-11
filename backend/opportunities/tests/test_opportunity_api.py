import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from audit.models import AuditLog
from common.throttles import ScopedThrottle
from jobs.models import JobDetail
from opportunities.models import Opportunity
from opportunities.tests.factories import make_job
from organizations.models import Organization
from organizations.tests.factories import MemberFactory, organization_with_roles
from taxonomy.models import Skill
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/opportunities/"
MINE = "/api/v1/users/me/opportunities/"


def detail(opportunity, action="") -> str:
    return f"{URL}{opportunity.pk}/{action}"


def skill_ids(*names) -> list[str]:
    return [str(pk) for pk in Skill.objects.filter(name__in=names).values_list("pk", flat=True)]


def in_days(days: int) -> str:
    return (timezone.now() + timedelta(days=days)).isoformat()


def payload(**overrides):
    """A complete job: enough to publish as it stands."""
    body = {
        "type": "JOB",
        "title": "Backend Engineer",
        "description": "Build and run our Django services.",
        "work_mode": "HYBRID",
        "country_code": "in",
        "city": "Kochi",
        "deadline": in_days(30),
        "skill_ids": skill_ids("Python", "Django"),
        "job": {
            "employment_type": "FULL_TIME",
            "experience_level": "MID",
            "salary_min": 800000,
            "salary_max": 1200000,
            "salary_currency": "inr",
            "salary_period": "YEAR",
            "openings": 2,
        },
    }
    return {**body, **overrides}


def actions(opportunity_id) -> list[str]:
    return list(
        AuditLog.objects.filter(target_id=opportunity_id)
        .order_by("created_at")
        .values_list("action", flat=True)
    )


# --- Create -----------------------------------------------------------------------------


def test_creating_a_personal_job_makes_a_draft_with_its_detail_row(api_as):
    user = UserFactory(display_name="Ada Lovelace")

    response = api_as(user).post(URL, payload())

    assert response.status_code == 201
    body = response.json()
    assert (body["type"], body["status"], body["visibility"]) == ("JOB", "DRAFT", "PUBLIC")
    assert (body["title"], body["country_code"], body["published_at"]) == (
        "Backend Engineer",
        "IN",
        None,
    )
    assert body["organization"] is None
    assert body["posted_by"]["display_name"] == "Ada Lovelace"
    assert [s["name"] for s in body["skills"]] == ["Django", "Python"]
    assert body["job"]["salary_currency"] == "INR"
    assert (body["job"]["application_method"], body["job"]["openings"]) == ("INTERNAL", 2)
    assert body["viewer"] == {
        "can_manage": True,
        "editable_fields": None,
        "is_saved": False,
        "can_apply": False,
        "application": None,
    }
    opportunity = Opportunity.objects.get(pk=body["id"])
    assert opportunity.creator == user
    assert JobDetail.objects.filter(opportunity=opportunity).exists()
    assert opportunity.skills_text == "Django Python"
    assert opportunity.search_vector is not None
    log = AuditLog.objects.get(action="opportunity.created")
    assert (log.actor, log.metadata) == (user, {"type": "JOB"})


def test_a_draft_needs_only_a_title(api_as):
    response = api_as(UserFactory()).post(URL, {"type": "JOB", "title": "  Rough   idea "})

    assert response.status_code == 201
    assert response.json()["title"] == "Rough idea"
    assert response.json()["job"]["employment_type"] == ""


def test_clients_cannot_set_server_controlled_fields(api_as):
    someone_else = UserFactory()

    response = api_as(UserFactory()).post(
        URL,
        payload(
            status="PUBLISHED",
            published_at=in_days(-1),
            moderation_status="REMOVED",
            creator=str(someone_else.pk),
        ),
    )

    opportunity = Opportunity.objects.get(pk=response.json()["id"])
    assert (opportunity.status, opportunity.published_at, opportunity.moderation_status) == (
        "DRAFT",
        None,
        "VISIBLE",
    )
    assert opportunity.creator != someone_else


def test_creating_requires_a_verified_account(api, api_as):
    anonymous = api.post(URL, payload())
    unverified = api_as(UserFactory(unverified=True)).post(URL, payload())

    assert anonymous.status_code == 401
    assert (unverified.status_code, unverified.json()["code"]) == (403, "email_not_verified")
    assert not Opportunity.objects.exists()


@pytest.mark.parametrize(
    ("who", "status"),
    [("OWNER", 201), ("ADMIN", 201), ("RECRUITER", 201), ("MEMBER", 403), ("outsider", 403)],
)
def test_who_may_post_on_behalf_of_an_organization(api_as, who, status):
    organization, members = organization_with_roles("ADMIN", "RECRUITER", "MEMBER")
    user = UserFactory() if who == "outsider" else members[who].user

    response = api_as(user).post(URL, payload(organization_id=str(organization.pk)))

    assert response.status_code == status
    if status == 201:
        body = response.json()
        assert body["organization"]["name"] == organization.name
        assert body["posted_by"] is None  # it speaks for the organization
        assert AuditLog.objects.get(action="opportunity.created").organization_id == organization.pk
    else:
        assert not Opportunity.objects.exists()


def test_posting_for_an_organization_needs_a_current_role_in_an_active_one(api_as):
    organization, members = organization_with_roles()
    former = MemberFactory(organization=organization, role="RECRUITER", status="LEFT")
    body = payload(organization_id=str(organization.pk))

    left = api_as(former.user).post(URL, body)
    missing = api_as(UserFactory()).post(URL, payload(organization_id=str(uuid.uuid7())))
    Organization.objects.filter(pk=organization.pk).update(status="SUSPENDED")
    suspended = api_as(members["OWNER"].user).post(URL, body)

    assert left.status_code == missing.status_code == 403
    assert (suspended.status_code, suspended.json()["code"]) == (422, "organization_suspended")


@pytest.mark.parametrize(
    ("overrides", "status", "field"),
    [
        ({"title": ""}, 400, "title"),
        ({"title": "!!!"}, 400, "title"),
        ({"type": "PARTY"}, 400, "type"),
        ({"country_code": "IND"}, 400, "country_code"),
        ({"work_mode": "MOON"}, 400, "work_mode"),
        ({"skill_ids": [str(uuid.uuid7()) for _ in range(16)]}, 400, "skill_ids"),
        ({"job": {"salary_min": 9, "salary_max": 5}}, 400, "job.salary_max"),
        ({"job": {"salary_currency": "RUPEES"}}, 400, "job.salary_currency"),
        ({"job": {"application_method": "EXTERNAL"}}, 400, "job.external_url"),
        ({"job": {"openings": 0}}, 400, "job.openings"),
        ({"job": {"employment_type": "FOREVER"}}, 400, "job.employment_type"),
        ({"visibility": "ORGANIZATION"}, 422, "visibility"),
        ({"skill_ids": [str(uuid.uuid7())]}, 422, "skill_ids"),
    ],
)
def test_create_validates_input(api_as, overrides, status, field):
    response = api_as(UserFactory()).post(URL, payload(**overrides))

    assert response.status_code == status
    assert list(response.json()["errors"]) == [field]
    assert not Opportunity.objects.exists()


def test_event_opportunities_are_not_available_yet(api_as):
    response = api_as(UserFactory()).post(URL, payload(type="EVENT"))

    assert (response.status_code, response.json()["code"]) == (422, "type_unavailable")


def test_creating_is_rate_limited(api_as, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "opportunity_create", "1/day")
    client = api_as(UserFactory())

    assert client.post(URL, payload()).status_code == 201
    assert client.post(URL, payload()).status_code == 429


# --- Edit a draft -----------------------------------------------------------------------


def test_everything_in_a_draft_can_be_edited(api_as):
    draft = make_job(job={"application_method": "EXTERNAL", "external_url": "https://x.example"})

    response = api_as(draft.creator).patch(
        detail(draft),
        {
            "title": "Senior Backend Engineer",
            "work_mode": "ONSITE",
            "city": "Kochi",
            "country_code": "in",
            "skill_ids": skill_ids("Django", "PostgreSQL"),
            "job": {"experience_level": "SENIOR", "application_method": "INTERNAL"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["title"], body["work_mode"], body["city"]) == (
        "Senior Backend Engineer",
        "ONSITE",
        "Kochi",
    )
    assert [s["name"] for s in body["skills"]] == ["Django", "PostgreSQL"]
    assert body["job"]["experience_level"] == "SENIOR"
    assert body["job"]["external_url"] == ""  # taking applications here clears the old link
    assert body["job"]["employment_type"] == "FULL_TIME"  # untouched fields stay
    draft.refresh_from_db()
    assert draft.skills_text == "Django PostgreSQL"
    log = AuditLog.objects.get(action="opportunity.updated")
    assert set(log.metadata["fields"]) >= {"title", "skill_ids", "job.experience_level"}


def test_an_edit_that_changes_nothing_is_not_audited(api_as):
    draft = make_job(title="Backend Engineer")

    response = api_as(draft.creator).patch(detail(draft), {"title": "Backend Engineer"})

    assert response.status_code == 200
    assert not AuditLog.objects.filter(action="opportunity.updated").exists()


def test_a_draft_is_invisible_to_everyone_but_its_managers(api, api_as):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    draft = make_job(creator=members["OWNER"].user, organization=organization)
    change = {"title": "Changed"}

    assert api.get(detail(draft)).status_code == 404
    assert api.patch(detail(draft), change).status_code == 401
    for outsider in (UserFactory(), members["MEMBER"].user):
        assert api_as(outsider).get(detail(draft)).status_code == 404
        assert api_as(outsider).patch(detail(draft), change).status_code == 404
        assert api_as(outsider).post(detail(draft, "publish/")).status_code == 404
        assert api_as(outsider).delete(detail(draft)).status_code == 404
    # Any recruiter of the organization manages it, not only whoever created it.
    assert api_as(members["RECRUITER"].user).patch(detail(draft), change).status_code == 200


def test_people_who_can_see_a_published_job_but_not_manage_it_are_refused(api_as):
    organization, members = organization_with_roles("MEMBER")
    job = make_job(status="PUBLISHED", creator=members["OWNER"].user, organization=organization)

    for user in (UserFactory(), members["MEMBER"].user):
        client = api_as(user)
        assert client.get(detail(job)).json()["viewer"] == {
            "can_manage": False,
            "editable_fields": [],
            "is_saved": False,
            # They cannot manage it, but they are free to apply to it.
            "can_apply": True,
            "application": None,
        }
        assert client.patch(detail(job), {"description": "Hacked"}).status_code == 403
        assert client.post(detail(job, "close/"), {"reason": "OTHER"}).status_code == 403
        assert client.post(detail(job, "archive/")).status_code == 403
    job.refresh_from_db()
    assert job.status == "PUBLISHED"


def test_leaving_the_organization_ends_management_of_its_opportunities(api_as):
    organization, members = organization_with_roles("RECRUITER")
    recruiter = members["RECRUITER"]
    job = make_job(status="PUBLISHED", creator=recruiter.user, organization=organization)
    client = api_as(recruiter.user)
    assert client.patch(detail(job), {"description": "Still mine."}).status_code == 200

    recruiter.status = "LEFT"
    recruiter.save()

    assert client.patch(detail(job), {"description": "No longer mine."}).status_code == 403
    assert client.get(MINE).json()["results"] == []


# --- Publish ----------------------------------------------------------------------------


def test_publishing_a_complete_draft(api_as):
    user = UserFactory()
    client = api_as(user)
    created = client.post(URL, payload()).json()

    response = client.post(f"{URL}{created['id']}/publish/")
    again = client.post(f"{URL}{created['id']}/publish/")

    assert response.status_code == again.status_code == 200
    body = response.json()
    assert body["status"] == "PUBLISHED"
    assert body["published_at"] is not None
    assert again.json()["published_at"] == body["published_at"]  # repeating changes nothing
    assert body["viewer"]["editable_fields"] == ["deadline", "description"]
    assert actions(created["id"]) == ["opportunity.created", "opportunity.published"]


def test_publishing_lists_everything_that_is_missing(api_as):
    client = api_as(UserFactory())
    created = client.post(
        URL, {"type": "JOB", "title": "Rough idea", "job": {"salary_min": 10}}
    ).json()

    response = client.post(f"{URL}{created['id']}/publish/")

    assert (response.status_code, response.json()["code"]) == (422, "incomplete")
    assert set(response.json()["errors"]) == {
        "description",
        "work_mode",
        "skill_ids",
        "job.employment_type",
        "job.experience_level",
        "job.salary_currency",
        "job.salary_period",
    }
    assert Opportunity.objects.get(pk=created["id"]).status == "DRAFT"


@pytest.mark.parametrize(
    ("fields", "missing"),
    [
        ({"work_mode": "HYBRID"}, {"country_code", "city"}),
        ({"work_mode": "ONSITE", "country_code": "IN"}, {"city"}),
        ({"work_mode": "REMOTE"}, set()),
        ({"deadline": timezone.now() - timedelta(hours=1)}, {"deadline"}),
        ({"deadline": None}, set()),
    ],
)
def test_publishing_checks_location_and_deadline(api_as, fields, missing):
    draft = make_job(**fields)

    response = api_as(draft.creator).post(detail(draft, "publish/"))

    if missing:
        assert set(response.json()["errors"]) == missing
    else:
        assert response.status_code == 200


def test_only_a_draft_can_be_published(api_as):
    for status in ("CLOSED", "EXPIRED", "ARCHIVED"):
        job = make_job(status=status)

        response = api_as(job.creator).post(detail(job, "publish/"))

        assert (response.status_code, response.json()["code"]) == (409, "invalid_transition")


def test_a_suspended_organization_cannot_publish(api_as):
    organization, members = organization_with_roles()
    draft = make_job(creator=members["OWNER"].user, organization=organization)
    Organization.objects.filter(pk=organization.pk).update(status="SUSPENDED")

    response = api_as(members["OWNER"].user).post(detail(draft, "publish/"))

    assert (response.status_code, response.json()["code"]) == (422, "organization_suspended")


# --- Edit after publishing --------------------------------------------------------------


def test_a_published_job_allows_only_safe_edits(api_as):
    job = make_job(status="PUBLISHED", title="Backend Engineer", deadline=None)
    client = api_as(job.creator)

    allowed = client.patch(
        detail(job),
        {"description": "Clearer wording.", "deadline": in_days(10), "job": {"openings": 3}},
    )
    refused = client.patch(
        detail(job),
        {
            "title": "Something Else",
            "work_mode": "ONSITE",
            "skill_ids": skill_ids("React"),
            "job": {"experience_level": "LEAD"},
        },
    )

    assert allowed.status_code == 200
    assert allowed.json()["job"]["openings"] == 3
    assert (refused.status_code, refused.json()["code"]) == (422, "locked_after_publish")
    assert set(refused.json()["errors"]) == {
        "title",
        "work_mode",
        "skill_ids",
        "job.experience_level",
    }
    job.refresh_from_db()
    assert (job.title, job.work_mode, job.description) == (
        "Backend Engineer",
        "REMOTE",
        "Clearer wording.",
    )


def test_a_form_may_send_back_unchanged_locked_fields(api_as):
    job = make_job(status="PUBLISHED")
    client = api_as(job.creator)
    current = client.get(detail(job)).json()

    response = client.patch(
        detail(job),
        {
            "title": current["title"],
            "work_mode": current["work_mode"],
            "skill_ids": [s["id"] for s in current["skills"]],
            "job": current["job"],
            "description": "Only this changed.",
        },
    )

    assert response.status_code == 200
    assert AuditLog.objects.get(action="opportunity.updated").metadata == {
        "fields": ["description"],
        "status": "PUBLISHED",
    }


def test_a_published_deadline_cannot_be_moved_into_the_past(api_as):
    job = make_job(status="PUBLISHED", deadline=timezone.now() + timedelta(days=5))

    response = api_as(job.creator).patch(detail(job), {"deadline": in_days(-1)})

    assert (response.status_code, response.json()["code"]) == (422, "deadline_passed")


# --- Close, archive, delete -------------------------------------------------------------


def test_closing_keeps_the_job_visible_and_stops_edits(api, api_as):
    job = make_job(status="PUBLISHED")
    client = api_as(job.creator)

    no_reason = client.post(detail(job, "close/"))
    closed = client.post(detail(job, "close/"), {"reason": "FILLED"})
    again = client.post(detail(job, "close/"), {"reason": "CANCELLED"})
    edit = client.patch(detail(job), {"description": "Too late."})

    assert (no_reason.status_code, list(no_reason.json()["errors"])) == (400, ["reason"])
    body = closed.json()
    assert (body["status"], body["close_reason"]) == ("CLOSED", "FILLED")
    assert body["closed_at"] is not None
    assert again.json()["close_reason"] == "FILLED"  # repeating does not rewrite the reason
    assert (edit.status_code, edit.json()["code"]) == (409, "opportunity_not_editable")
    assert api.get(detail(job)).json()["status"] == "CLOSED"
    assert AuditLog.objects.get(action="opportunity.closed").metadata == {"reason": "FILLED"}


def test_only_a_published_job_can_be_closed(api_as):
    for status in ("DRAFT", "EXPIRED", "ARCHIVED"):
        job = make_job(status=status)

        response = api_as(job.creator).post(detail(job, "close/"), {"reason": "OTHER"})

        assert response.status_code == 409


def test_archiving_takes_a_finished_job_out_of_public_view(api, api_as):
    for status in ("CLOSED", "EXPIRED"):
        job = make_job(status=status)
        assert api.get(detail(job)).status_code == 200

        response = api_as(job.creator).post(detail(job, "archive/"))

        assert response.json()["status"] == "ARCHIVED"
        assert api.get(detail(job)).status_code == 404
        assert api_as(UserFactory()).get(detail(job)).status_code == 404
        assert api_as(job.creator).get(detail(job)).status_code == 200


def test_a_live_job_must_be_closed_before_archiving(api_as):
    for status in ("DRAFT", "PUBLISHED"):
        job = make_job(status=status)

        assert api_as(job.creator).post(detail(job, "archive/")).status_code == 409


def test_only_drafts_can_be_deleted(api_as):
    draft, published = make_job(), make_job(status="PUBLISHED")

    deleted = api_as(draft.creator).delete(detail(draft))
    refused = api_as(published.creator).delete(detail(published))

    assert deleted.status_code == 204
    assert not Opportunity.objects.filter(pk=draft.pk).exists()
    assert not JobDetail.objects.filter(pk=draft.pk).exists()
    assert actions(draft.pk) == ["opportunity.deleted"]  # the record outlives the draft
    assert (refused.status_code, refused.json()["code"]) == (409, "not_a_draft")
    assert Opportunity.objects.filter(pk=published.pk).exists()


# --- My opportunities -------------------------------------------------------------------


def test_my_opportunities_lists_everything_i_manage_in_every_state(api, api_as):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    recruiter = members["RECRUITER"].user
    mine = [make_job(status=status, creator=recruiter) for status in ("DRAFT", "ARCHIVED")]
    organizations = make_job(
        status="PUBLISHED", creator=members["OWNER"].user, organization=organization
    )
    make_job(status="PUBLISHED")  # somebody else's

    def ids(client, **params):
        return {o["id"] for o in client.get(MINE, params).json()["results"]}

    client = api_as(recruiter)
    assert ids(client) == {str(o.pk) for o in [*mine, organizations]}
    assert ids(client, status="DRAFT") == {str(mine[0].pk)}
    assert ids(api_as(members["MEMBER"].user)) == set()
    assert client.get(MINE, {"status": "LIVE"}).status_code == 400
    assert api.get(MINE).status_code == 401


def test_my_opportunities_uses_a_fixed_number_of_queries(api_as, django_assert_max_num_queries):
    user = UserFactory()
    for _ in range(8):
        make_job(creator=user, skills=("Python", "Django", "React"))

    with django_assert_max_num_queries(4):
        assert len(api_as(user).get(MINE).json()["results"]) == 8
