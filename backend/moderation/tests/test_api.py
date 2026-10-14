import threading
import uuid

import pytest
from django.db import IntegrityError, connection, transaction

from audit.models import AuditLog
from common.throttles import ScopedThrottle
from communities.tests.factories import CommunityFactory, community_with_roles
from moderation import services
from moderation.models import ModerationAction, Report
from notifications.models import Notification
from opportunities.models import Opportunity
from opportunities.tests.factories import make_job
from organizations.tests.factories import OrganizationFactory, organization_with_roles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

REPORTS = "/api/v1/reports/"
QUEUE = "/api/v1/moderation/reports/"
ACTIONS = "/api/v1/moderation/actions/"


def moderator(**fields):
    return UserFactory(platform_role="MODERATOR", **fields)


def body(target, target_type="OPPORTUNITY", **overrides):
    return {
        "target_type": target_type,
        "target_id": str(target.pk),
        "category": "SCAM",
        "description": "Asks for money to apply.",
        **overrides,
    }


def report_on(target, reporter=None, target_type="OPPORTUNITY", **fields) -> Report:
    """A report written directly, so tests can start from any state."""
    field = {
        "OPPORTUNITY": "target_opportunity",
        "USER": "target_user",
        "ORGANIZATION": "target_organization",
        "COMMUNITY": "target_community",
    }[target_type]
    return Report.objects.create(
        reporter=reporter or UserFactory.create(),
        target_type=target_type,
        category="SPAM",
        **{field: target},
        **fields,
    )


def one(report, action="") -> str:
    return f"{QUEUE}{report.pk}/{action}"


# --- Reporting --------------------------------------------------------------------------


def test_reporting_an_opportunity(api_as):
    job, reporter = make_job(status="PUBLISHED", title="Backend Engineer"), UserFactory()

    response = api_as(reporter).post(REPORTS, body(job))

    assert response.status_code == 201
    data = response.json()
    assert data["target"] == {
        "type": "OPPORTUNITY",
        "id": str(job.pk),
        "name": "Backend Engineer",
        "url": f"/opportunities/{job.pk}",
    }
    assert (data["status"], data["category"]) == ("OPEN", "SCAM")
    # Nothing a moderator writes, and not who else is involved.
    assert set(data) == {
        "id",
        "target",
        "category",
        "description",
        "status",
        "created_at",
        "resolved_at",
    }
    report = Report.objects.get()
    assert (report.reporter, report.target) == (reporter, job)
    log = AuditLog.objects.get(action="report.filed")
    assert log.metadata == {
        "target_type": "OPPORTUNITY",
        "target_id": str(job.pk),
        "category": "SCAM",
    }
    # Reporting changes nothing by itself, and tells nobody.
    assert Opportunity.objects.get(pk=job.pk).moderation_status == "VISIBLE"
    assert not Notification.objects.exists()


def test_people_organizations_and_communities_can_be_reported_too(api_as):
    reporter = api_as(UserFactory())
    person, organization, community = UserFactory(), OrganizationFactory(), CommunityFactory()

    for target, kind in (
        (person, "USER"),
        (organization, "ORGANIZATION"),
        (community, "COMMUNITY"),
    ):
        response = reporter.post(REPORTS, body(target, kind))
        assert response.status_code == 201, response.content
        assert response.json()["target"]["type"] == kind
        assert response.json()["target"]["url"].endswith(str(target.pk))
    assert Report.objects.count() == 3


def test_one_report_at_a_time_about_the_same_thing(api_as):
    job, reporter = make_job(status="PUBLISHED"), UserFactory()
    client = api_as(reporter)
    first = client.post(REPORTS, body(job))

    again = client.post(REPORTS, body(job, category="SPAM"))

    assert (again.status_code, again.json()["code"]) == (409, "already_reported")
    # Someone else can, and so can the same person once theirs has been decided.
    assert api_as(UserFactory()).post(REPORTS, body(job)).status_code == 201
    Report.objects.filter(pk=first.json()["id"]).update(status="DISMISSED")
    assert client.post(REPORTS, body(job)).status_code == 201
    assert Report.objects.count() == 3


def test_what_cannot_be_reported(api, api_as):
    organization, members = organization_with_roles("RECRUITER")
    theirs = make_job(status="PUBLISHED", organization=organization, creator=members["OWNER"].user)
    mine, me = make_job(status="PUBLISHED"), UserFactory()
    client = api_as(me)

    # Yourself, and what you manage.
    own = [
        api_as(mine.creator).post(REPORTS, body(mine)),
        api_as(members["RECRUITER"].user).post(REPORTS, body(theirs)),
        client.post(REPORTS, body(me, "USER")),
    ]
    assert [(r.status_code, r.json()["code"]) for r in own] == [(422, "own_content")] * 3
    # What you cannot see, or what does not exist.
    for hidden, kind in (
        (make_job(), "OPPORTUNITY"),
        (make_job(status="PUBLISHED", moderation_status="HIDDEN"), "OPPORTUNITY"),
        (CommunityFactory(visibility="PRIVATE"), "COMMUNITY"),
    ):
        assert client.post(REPORTS, body(hidden, kind)).status_code == 404
    missing = {**body(mine), "target_id": str(uuid.uuid4())}
    assert client.post(REPORTS, missing).status_code == 404
    # A job's ID is not a person's.
    assert client.post(REPORTS, body(mine, "USER")).status_code == 404
    assert api.post(REPORTS, body(mine)).status_code == 401
    unverified = api_as(UserFactory(unverified=True)).post(REPORTS, body(mine))
    assert (unverified.status_code, unverified.json()["code"]) == (403, "email_not_verified")
    assert not Report.objects.exists()


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"target_type": "MESSAGE"}, "target_type"),
        ({"category": "BORING"}, "category"),
        ({"target_id": "nope"}, "target_id"),
        ({"description": "x" * 2001}, "description"),
    ],
)
def test_report_validates_input(api_as, overrides, field):
    job = make_job(status="PUBLISHED")

    response = api_as(UserFactory()).post(REPORTS, body(job, **overrides))

    assert (response.status_code, list(response.json()["errors"])) == (400, [field])


def test_reporting_is_rate_limited(api_as, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "report_create", "2/day")
    client = api_as(UserFactory())

    codes = [client.post(REPORTS, body(make_job(status="PUBLISHED"))).status_code for _ in range(3)]

    assert codes == [201, 201, 429]


def test_my_reports_shows_only_mine_and_only_that_they_were_decided(api, api_as):
    me, job = UserFactory(), make_job(status="PUBLISHED")
    mine = report_on(job, me, status="DISMISSED", resolution_note="Looks fine to me.")
    report_on(job)

    response = api_as(me).get(f"{REPORTS}mine/")

    (row,) = response.json()["results"]
    assert (row["id"], row["status"]) == (str(mine.pk), "DISMISSED")
    assert "Looks fine to me." not in response.content.decode()
    assert "reporter" not in row and "resolution_note" not in row
    assert api.get(f"{REPORTS}mine/").status_code == 401


# --- The queue --------------------------------------------------------------------------


def test_the_queue_is_for_platform_moderators_only(api, api_as):
    organization, members = organization_with_roles()
    _, community_members = community_with_roles("MODERATOR")
    report = report_on(make_job(status="PUBLISHED"))

    assert api.get(QUEUE).status_code == 401
    # Owning an organization, moderating a community, or anything else short of a platform
    # role, gives nothing.
    for user in (
        UserFactory(),
        members["OWNER"].user,
        report.reporter,
        community_members["OWNER"].user,
        community_members["MODERATOR"].user,
    ):
        client = api_as(user)
        assert client.get(QUEUE).status_code == 403
        assert client.get(one(report)).status_code == 403
        for action in ("claim/", "dismiss/", "resolve/"):
            assert client.post(one(report, action), {}).status_code == 403
        assert client.post(ACTIONS, {}).status_code == 403
    report.refresh_from_db()
    assert report.status == "OPEN"
    for role in ("MODERATOR", "ADMIN"):
        assert api_as(UserFactory(platform_role=role)).get(QUEUE).status_code == 200
    # A deactivated moderator is no longer one.
    assert api_as(moderator(is_active=False)).get(QUEUE).status_code in (401, 403)


def test_the_queue_lists_the_longest_waiting_first_and_filters(
    api_as, django_assert_max_num_queries
):
    job = make_job(status="PUBLISHED")
    oldest = report_on(job)
    about_person = report_on(UserFactory(), target_type="USER")
    decided = report_on(job, status="DISMISSED")
    client = api_as(moderator())

    rows = client.get(QUEUE).json()["results"]
    assert [row["id"] for row in rows] == [str(r.pk) for r in (oldest, about_person, decided)]
    assert rows[0]["reporter"]["id"] == str(oldest.reporter.pk)
    assert rows[1]["target"]["type"] == "USER"

    def ids(**params):
        return [row["id"] for row in client.get(QUEUE, params).json()["results"]]

    assert ids(status="OPEN") == [str(oldest.pk), str(about_person.pk)]
    assert ids(target_type="USER") == [str(about_person.pk)]
    assert ids(status="DISMISSED", target_type="OPPORTUNITY") == [str(decided.pk)]
    assert client.get(QUEUE, {"status": "nope"}).status_code == 400

    for _ in range(8):
        report_on(make_job(status="PUBLISHED"))
    with django_assert_max_num_queries(4):
        assert len(client.get(QUEUE).json()["results"]) == 11


def test_a_report_shows_what_a_moderator_needs_to_decide(api_as):
    job = make_job(status="PUBLISHED")
    report = report_on(job)
    report_on(job)
    report_on(job, status="DISMISSED")
    about_person = report_on(UserFactory(), target_type="USER")
    client = api_as(moderator())

    detail = client.get(one(report)).json()

    assert detail["in_progress_on_target"] == 2
    assert detail["available_actions"] == ["HIDE", "REMOVE"]
    assert detail["actions"] == []
    # A moderator can warn a person or stop them posting; suspending is for admins.
    assert client.get(one(about_person)).json()["available_actions"] == [
        "RESTRICT_POSTING",
        "WARN",
    ]
    assert api_as(UserFactory(platform_role="ADMIN")).get(one(about_person)).json()[
        "available_actions"
    ] == ["RESTRICT_POSTING", "SUSPEND", "WARN"]
    assert client.get(f"{QUEUE}{uuid.uuid4()}/").status_code == 404


# --- Deciding ---------------------------------------------------------------------------


def test_claiming_a_report(api_as):
    staff, report = moderator(), report_on(make_job(status="PUBLISHED"))
    client = api_as(staff)

    response = client.post(one(report, "claim/"))

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["assigned_to"]["id"]) == (
        "UNDER_REVIEW",
        str(staff.pk),
    )
    # Claiming again, even by a colleague, changes nothing.
    assert api_as(moderator()).post(one(report, "claim/")).json()["assigned_to"]["id"] == str(
        staff.pk
    )
    assert AuditLog.objects.filter(action="report.claimed").count() == 1


def test_dismissing_a_report_tells_the_reporter_without_saying_what_was_decided(api_as):
    staff, report = moderator(), report_on(make_job(status="PUBLISHED"))

    response = api_as(staff).post(one(report, "dismiss/"), {"note": "Ordinary job advert."})

    assert response.status_code == 200
    data = response.json()
    assert (data["status"], data["resolution_note"], data["available_actions"]) == (
        "DISMISSED",
        "Ordinary job advert.",
        [],
    )
    report.refresh_from_db()
    assert (report.resolved_by, report.resolved_at is not None) == (staff, True)
    notice = Notification.objects.get()
    assert (notice.recipient, notice.type, notice.actor) == (
        report.reporter,
        "REPORT_REVIEWED",
        None,
    )
    listed = api_as(report.reporter).get("/api/v1/notifications/").json()["results"][0]
    assert "Ordinary job advert." not in str(listed) and "ismiss" not in str(listed)
    assert AuditLog.objects.get(action="report.resolved").metadata == {"outcome": "DISMISSED"}

    # A decided report cannot be decided again.
    again = api_as(staff).post(one(report, "dismiss/"), {})
    assert again.status_code == 200  # the same outcome is simply repeated
    late = api_as(staff).post(one(report, "resolve/"), {"action": "HIDE", "reason": "Scam."})
    assert late.status_code == 409
    assert Notification.objects.count() == 1


def test_hiding_a_reported_opportunity(api, api_as):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    job = make_job(
        status="PUBLISHED",
        title="Easy money",
        organization=organization,
        creator=members["OWNER"].user,
    )
    other_job = make_job(status="PUBLISHED")
    report, second = report_on(job), report_on(job)
    elsewhere = report_on(other_job)
    staff = moderator()

    response = api_as(staff).post(
        one(report, "resolve/"), {"action": "HIDE", "reason": "Asks applicants for a fee."}
    )

    assert response.status_code == 200
    data = response.json()
    assert (data["status"], data["available_actions"]) == ("ACTION_TAKEN", [])
    assert [(a["action_type"], a["reason"]) for a in data["actions"]] == [
        ("HIDE", "Asks applicants for a fee.")
    ]
    assert data["actions"][0]["actor"]["id"] == str(staff.pk)

    # Gone for everyone but the people who run it, who see why.
    url = f"/api/v1/opportunities/{job.pk}/"
    assert api.get(url).status_code == 404
    assert api_as(UserFactory()).get(url).status_code == 404
    assert api_as(members["MEMBER"].user).get(url).status_code == 404
    assert str(job.pk) not in api.get("/api/v1/opportunities/").content.decode()
    assert api_as(members["OWNER"].user).get(url).json()["moderation_status"] == "HIDDEN"
    assert api_as(staff).get(url).status_code == 200

    # Every report about it is settled, and nothing else is touched.
    second.refresh_from_db()
    elsewhere.refresh_from_db()
    assert (second.status, elsewhere.status) == ("ACTION_TAKEN", "OPEN")
    told = {(n.recipient_id, n.type) for n in Notification.objects.all()}
    assert told == {
        (report.reporter_id, "REPORT_REVIEWED"),
        (second.reporter_id, "REPORT_REVIEWED"),
        (members["OWNER"].user.pk, "OPPORTUNITY_MODERATED"),
        (members["RECRUITER"].user.pk, "OPPORTUNITY_MODERATED"),
    }
    owner_notice = api_as(members["OWNER"].user).get("/api/v1/notifications/").json()["results"][0]
    assert owner_notice["title"] == "A moderator has hidden “Easy money”"
    assert "Asks applicants for a fee." in owner_notice["body"]
    # The owners are not told who reported it.
    assert str(report.reporter_id) not in str(owner_notice)

    action = ModerationAction.objects.get()
    assert (action.report, action.target) == (report, job)
    log = AuditLog.objects.get(action="moderation.action_taken")
    assert (log.actor, log.target_id, log.organization_id) == (staff, job.pk, organization.pk)
    assert log.metadata["action"] == "HIDE"

    # Hidden can still be removed, in answer to a later report, but not hidden twice.
    later = report_on(job, status="OPEN")
    assert api_as(staff).get(one(later)).json()["available_actions"] == ["REMOVE"]
    twice = api_as(staff).post(one(later, "resolve/"), {"action": "HIDE", "reason": "Again."})
    assert (twice.status_code, twice.json()["code"]) == (409, "action_not_possible")


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"action": "RESTORE", "reason": "Fine."}, 422, "action_unavailable"),
        ({"action": "HIDE", "reason": "   "}, 400, "validation_error"),
        ({"action": "HIDE"}, 400, "validation_error"),
        ({"action": "DELETE", "reason": "x"}, 400, "validation_error"),
    ],
)
def test_resolve_validates_input(api_as, payload, status, code):
    report = report_on(make_job(status="PUBLISHED"))

    response = api_as(moderator()).post(one(report, "resolve/"), payload)

    assert (response.status_code, response.json()["code"]) == (status, code)
    report.refresh_from_db()
    assert report.status == "OPEN" and not ModerationAction.objects.exists()


def test_an_action_meant_for_another_kind_of_thing_is_refused(api_as):
    report = report_on(UserFactory(), target_type="USER")

    response = api_as(moderator()).post(
        one(report, "resolve/"), {"action": "HIDE", "reason": "Rude."}
    )

    assert (response.status_code, response.json()["code"]) == (422, "action_unavailable")


def test_a_moderator_does_not_decide_a_report_they_are_part_of(api_as):
    staff, colleague = moderator(), moderator()
    filed_by_staff = report_on(make_job(status="PUBLISHED"), staff)
    about_staff = report_on(staff, target_type="USER")

    for report in (filed_by_staff, about_staff):
        client = api_as(staff)
        assert client.post(one(report, "claim/")).status_code == 403
        assert client.post(one(report, "dismiss/"), {}).status_code == 403
        report.refresh_from_db()
        assert report.status == "OPEN"
    refused = api_as(staff).post(
        one(filed_by_staff, "resolve/"), {"action": "HIDE", "reason": "Mine."}
    )
    assert refused.status_code == 403
    assert not ModerationAction.objects.exists()
    # A colleague can.
    assert api_as(colleague).post(one(filed_by_staff, "dismiss/"), {}).status_code == 200


# --- Acting without a report ------------------------------------------------------------


def act(client, job, action, reason="For the record."):
    return client.post(
        ACTIONS,
        {
            "target_type": "OPPORTUNITY",
            "target_id": str(job.pk),
            "action": action,
            "reason": reason,
        },
    )


def test_hiding_and_restoring_without_a_report(api, api_as):
    job = make_job(status="PUBLISHED", title="Backend Engineer")
    waiting = report_on(job)
    staff = api_as(moderator())
    url = f"/api/v1/opportunities/{job.pk}/"

    hidden = act(staff, job, "HIDE")
    assert hidden.status_code == 201 and hidden.json()["action_type"] == "HIDE"
    assert api.get(url).status_code == 404
    # A report that was waiting about it is settled by the same act.
    waiting.refresh_from_db()
    assert waiting.status == "ACTION_TAKEN"

    restored = act(staff, job, "RESTORE", "Fixed by the poster.")
    assert restored.status_code == 201
    assert api.get(url).status_code == 200
    titles = [
        n["title"] for n in api_as(job.creator).get("/api/v1/notifications/").json()["results"]
    ]
    assert titles == [
        "“Backend Engineer” is visible again",
        "A moderator has hidden “Backend Engineer”",
    ]
    assert [a.action_type for a in ModerationAction.objects.order_by("created_at")] == [
        "HIDE",
        "RESTORE",
    ]


def test_what_cannot_be_done_to_an_opportunity(api_as):
    job, staff = make_job(status="PUBLISHED"), api_as(moderator())

    assert act(staff, job, "RESTORE").json()["code"] == "action_not_possible"  # not hidden
    assert act(staff, job, "REMOVE").status_code == 201
    # Removing is final.
    for action in ("RESTORE", "HIDE", "REMOVE"):
        response = act(staff, job, action)
        assert (response.status_code, response.json()["code"]) == (409, "action_not_possible")
    assert Opportunity.objects.get(pk=job.pk).moderation_status == "REMOVED"
    missing = staff.post(
        ACTIONS,
        {
            "target_type": "OPPORTUNITY",
            "target_id": str(uuid.uuid4()),
            "action": "HIDE",
            "reason": "x",
        },
    )
    assert missing.status_code == 404
    person = staff.post(
        ACTIONS,
        {
            "target_type": "USER",
            "target_id": str(UserFactory().pk),
            "action": "HIDE",
            "reason": "x",
        },
    )
    assert (person.status_code, person.json()["code"]) == (422, "action_unavailable")


# --- The database's own rules -----------------------------------------------------------


def test_the_database_refuses_what_the_service_never_does():
    job, person, staff = make_job(status="PUBLISHED"), UserFactory(), moderator()
    about = {"reporter": UserFactory(), "category": "SPAM"}

    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.create(target_type="OPPORTUNITY", **about)  # about nothing
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.create(
            target_type="OPPORTUNITY", target_opportunity=job, target_user=person, **about
        )  # about two things
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.create(target_type="USER", target_opportunity=job, **about)  # mislabelled
    with pytest.raises(IntegrityError), transaction.atomic():
        ModerationAction.objects.create(
            actor=staff,
            action_type="HIDE",
            target_type="OPPORTUNITY",
            target_opportunity=job,
            reason="",
        )


# --- Races ------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_moderators_deciding_at_once_leave_one_decision():
    job = make_job(status="PUBLISHED")
    report = report_on(job)
    first, second = moderator(), moderator()
    barrier = threading.Barrier(2)
    outcomes = []

    def run(call):
        barrier.wait()
        try:
            call()
            outcomes.append("done")
        except Exception as exc:
            outcomes.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [
        threading.Thread(
            target=run,
            args=(
                lambda: services.act(
                    actor=first,
                    target_type="OPPORTUNITY",
                    target_id=job.pk,
                    action="HIDE",
                    reason="Scam.",
                    report_id=report.pk,
                ),
            ),
        ),
        threading.Thread(
            target=run,
            args=(lambda: services.dismiss(actor=second, report_id=report.pk, note="Fine."),),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    report.refresh_from_db()
    job.refresh_from_db()
    # Whoever got there first decided; the report and the job agree with each other.
    assert (report.status, job.moderation_status) in {
        ("ACTION_TAKEN", "HIDDEN"),
        ("DISMISSED", "VISIBLE"),
    }
    assert AuditLog.objects.filter(action="report.resolved").count() == 1
    assert Notification.objects.filter(type="REPORT_REVIEWED").count() == 1
