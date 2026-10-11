"""The employer's side: a job's applications, and moving them through the stages."""

import pytest
from django.core import mail

from applications import policies, services
from applications.models import Application, ApplicationStatus, ApplicationStatusHistory
from applications.policies import Actor
from applications.tests.factories import make_application
from audit.models import AuditLog
from common.errors import InvalidTransition, StaleState
from communities.tests.test_concurrency import errors, run_together
from notifications import services as notifications
from notifications.models import Category, Notification
from opportunities.tests.factories import make_job
from organizations.tests.factories import MemberFactory, organization_with_roles
from realtime import events
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

S = ApplicationStatus


def organization_job(**fields):
    organization, members = organization_with_roles("ADMIN", "RECRUITER", "MEMBER")
    job = make_job(
        status="PUBLISHED", organization=organization, creator=members["RECRUITER"].user, **fields
    )
    return job, {role: member.user for role, member in members.items()}


def pipeline_url(job, suffix="") -> str:
    return f"/api/v1/jobs/{job.pk}/applications/{suffix}"


def move_url(application) -> str:
    return f"/api/v1/applications/{application.pk}/transition/"


def move(client, application, to, expected=None, **body):
    body = {"to": to, "expected_status": expected or application.status, **body}
    return client.post(move_url(application), body)


# --- Rules ------------------------------------------------------------------------------


def test_nobody_decides_on_their_own_application():
    recruiter = Actor(is_applicant=False, is_manager=True)
    applicant = Actor(is_applicant=True, is_manager=False)
    # Applied first, joined the hiring team later.
    both = Actor(is_applicant=True, is_manager=True)
    application = Application(status=S.SCREENING)

    assert policies.decides(recruiter)
    assert not policies.decides(applicant) and not policies.decides(both)
    assert policies.can_read_notes(recruiter)
    assert not policies.can_read_notes(applicant) and not policies.can_read_notes(both)
    assert policies.next_statuses(recruiter, application) == [
        "SHORTLISTED",
        "INTERVIEW",
        "OFFER",
        "HIRED",
        "REJECTED",
    ]
    assert policies.next_statuses(applicant, application) == []
    assert policies.next_statuses(both, application) == []
    # They can still withdraw it, like any applicant.
    assert policies.can_withdraw(both, application)


@pytest.mark.parametrize("status", ["HIRED", "REJECTED", "WITHDRAWN"])
def test_a_decided_application_offers_no_further_moves(status):
    recruiter = Actor(is_applicant=False, is_manager=True)

    assert policies.next_statuses(recruiter, Application(status=status)) == []


def test_the_offered_moves_are_exactly_the_ones_the_state_machine_allows():
    recruiter = Actor(is_applicant=False, is_manager=True)

    for status in S.values:
        offered = set(policies.next_statuses(recruiter, Application(status=status)))
        assert offered == policies.PIPELINE.targets(status) - {"WITHDRAWN"}
        assert offered <= services.MANAGER_TARGETS


# --- The pipeline -----------------------------------------------------------------------


def test_the_people_who_manage_a_job_see_its_applications(api_as, django_assert_max_num_queries):
    job, people = organization_job()
    first = make_application(opportunity=job, headline="Python developer")
    second = make_application(opportunity=job, status="INTERVIEW")
    make_application()  # to another job
    client = api_as(people["RECRUITER"])

    response = client.get(pipeline_url(job))

    assert response.status_code == 200
    rows = response.json()["results"]
    assert [row["id"] for row in rows] == [str(second.pk), str(first.pk)]
    assert rows[1] == {
        "id": str(first.pk),
        "status": "APPLIED",
        "created_at": rows[1]["created_at"],
        "status_changed_at": rows[1]["status_changed_at"],
        "headline": "Python developer",
        "applicant": {
            "id": str(first.applicant.pk),
            "display_name": first.applicant.profile.display_name,
            "headline": first.applicant.profile.headline,
            "avatar_url": None,
        },
        "next_statuses": ["SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER", "HIRED", "REJECTED"],
    }
    assert rows[0]["next_statuses"] == ["OFFER", "HIRED", "REJECTED"]

    only = client.get(pipeline_url(job), {"status": "INTERVIEW"}).json()["results"]
    assert [row["id"] for row in only] == [str(second.pk)]
    assert client.get(pipeline_url(job), {"status": "nonsense"}).status_code == 400

    for _ in range(6):
        make_application(opportunity=job)
    with django_assert_max_num_queries(6):
        assert len(client.get(pipeline_url(job)).json()["results"]) == 8


def test_the_summary_counts_every_stage(api_as):
    job, people = organization_job(job={"openings": 3})
    for status in ("APPLIED", "APPLIED", "INTERVIEW", "HIRED", "WITHDRAWN"):
        make_application(opportunity=job, status=status)
    make_application(status="HIRED")  # another job's

    response = api_as(people["ADMIN"]).get(pipeline_url(job, "summary/"))

    assert response.status_code == 200
    assert response.json() == {
        "counts": {
            "APPLIED": 2,
            "SCREENING": 0,
            "SHORTLISTED": 0,
            "INTERVIEW": 1,
            "OFFER": 0,
            "HIRED": 1,
            "REJECTED": 0,
            "WITHDRAWN": 1,
        },
        "total": 5,
        "openings": 3,
    }


def test_who_may_see_a_jobs_applications(api, api_as):
    job, people = organization_job()
    personal = make_job(status="PUBLISHED")
    applicant = make_application(opportunity=job).applicant
    hidden = make_job(status="DRAFT")

    for path in ("", "summary/"):
        url = pipeline_url(job, path)
        for role in ("OWNER", "ADMIN", "RECRUITER"):
            assert api_as(people[role]).get(url).status_code == 200
        # They can see the job, so they are told plainly that this part is not theirs.
        for outsider in (people["MEMBER"], applicant, UserFactory()):
            assert api_as(outsider).get(url).status_code == 403
        assert api_as(UserFactory(platform_role="ADMIN")).get(url).status_code == 403
        assert api.get(url).status_code == 401
        # A job they cannot see at all does not exist for them.
        assert api_as(UserFactory()).get(pipeline_url(hidden, path)).status_code == 404
        assert api_as(personal.creator).get(pipeline_url(personal, path)).status_code == 200
        assert api_as(people["OWNER"]).get(pipeline_url(personal, path)).status_code == 403


def test_a_manager_still_sees_the_applications_of_a_closed_or_archived_job(api_as):
    for status in ("CLOSED", "EXPIRED", "ARCHIVED"):
        job = make_job(status=status)
        make_application(opportunity=job)

        response = api_as(job.creator).get(pipeline_url(job))

        assert len(response.json()["results"]) == 1


# --- Moving an application --------------------------------------------------------------


def test_moving_an_application_forward_records_it_and_tells_the_applicant(
    api_as, django_capture_on_commit_callbacks
):
    job, people = organization_job(title="Backend Engineer")
    application = make_application(opportunity=job)
    recruiter = api_as(people["RECRUITER"])

    with django_capture_on_commit_callbacks(execute=True):
        response = move(recruiter, application, "INTERVIEW", note="Strong on SQL; skip the screen.")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INTERVIEW"
    assert body["viewer"]["next_statuses"] == ["OFFER", "HIRED", "REJECTED"]
    step = body["history"][-1]
    assert (step["from_status"], step["to_status"]) == ("APPLIED", "INTERVIEW")
    assert step["note"] == "Strong on SQL; skip the screen."
    assert step["actor"]["id"] == str(people["RECRUITER"].pk)

    application.refresh_from_db()
    assert application.status == "INTERVIEW"
    log = AuditLog.objects.get(action="application.status_changed")
    assert (log.actor, log.target_id, log.organization_id) == (
        people["RECRUITER"],
        application.pk,
        job.organization_id,
    )
    # What was decided is audited; what was said about the person is not copied there.
    assert log.metadata == {"from": "APPLIED", "to": "INTERVIEW"}

    notice = Notification.objects.get(recipient=application.applicant)
    assert notice.type == "APPLICATION_ADVANCED"
    assert notice.actor is None
    assert "Strong on SQL" not in str(notice.payload)
    listed = api_as(application.applicant).get("/api/v1/notifications/").json()["results"][0]
    assert listed["title"] == "Your application to “Backend Engineer” moved to Interview"
    assert listed["url"] == f"/applications/{application.pk}"
    assert listed["actor"] is None
    (email,) = mail.outbox
    assert email.to == [application.applicant.email]
    assert "moved to Interview" in email.subject


def test_hiring_and_rejecting_have_their_own_words(api_as):
    job = make_job(status="PUBLISHED", title="Backend Engineer")
    hired = make_application(opportunity=job, status="OFFER")
    rejected = make_application(opportunity=job, status="SCREENING")
    client = api_as(job.creator)

    assert move(client, hired, "HIRED").json()["viewer"]["next_statuses"] == []
    assert move(client, rejected, "REJECTED", note="Not enough experience.").status_code == 200

    def told(application):
        client = api_as(application.applicant)
        return client.get("/api/v1/notifications/").json()["results"][0]

    assert told(hired)["title"] == "You were selected for “Backend Engineer”"
    assert told(rejected)["title"] == "Your application to “Backend Engineer” was not selected"
    assert Notification.objects.get(recipient=rejected.applicant).type == "APPLICATION_REJECTED"
    # The reason stays with the employer.
    assert "experience" not in told(rejected)["body"]


def test_the_applicant_never_sees_who_moved_them_or_what_was_noted(api_as):
    job, people = organization_job()
    application = make_application(opportunity=job)
    move(api_as(people["ADMIN"]), application, "SCREENING", note="Came recommended by Sam.")

    response = api_as(application.applicant).get(f"/api/v1/applications/{application.pk}/")

    assert [(s["to_status"], s["note"], s["actor"]) for s in response.json()["history"]] == [
        ("APPLIED", "", None),
        ("SCREENING", "", None),
    ]
    assert "Sam" not in response.content.decode()
    assert str(people["ADMIN"].pk) not in response.content.decode()
    # A colleague of the person who wrote it does see it.
    theirs = api_as(people["RECRUITER"]).get(f"/api/v1/applications/{application.pk}/")
    assert theirs.json()["history"][-1]["note"] == "Came recommended by Sam."


@pytest.mark.parametrize(
    ("status", "to", "code"),
    [
        ("INTERVIEW", "SCREENING", "invalid_transition"),  # backwards
        ("HIRED", "REJECTED", "invalid_transition"),
        ("REJECTED", "INTERVIEW", "invalid_transition"),  # no way back from a decision
        ("WITHDRAWN", "INTERVIEW", "invalid_transition"),
        ("WITHDRAWN", "REJECTED", "invalid_transition"),
    ],
)
def test_moves_that_are_never_allowed(api_as, status, to, code):
    application = make_application(status=status)

    response = move(api_as(application.opportunity.creator), application, to)

    assert (response.status_code, response.json()["code"]) == (409, code)
    application.refresh_from_db()
    assert application.status == status
    assert not Notification.objects.exists()


def test_a_move_made_on_an_outdated_view_is_refused(api_as):
    job, people = organization_job()
    application = make_application(opportunity=job)
    assert move(api_as(people["ADMIN"]), application, "REJECTED").status_code == 200

    # The recruiter's page still shows it as "Applied".
    response = move(api_as(people["RECRUITER"]), application, "INTERVIEW", expected="APPLIED")

    assert (response.status_code, response.json()["code"]) == (409, "stale_state")
    application.refresh_from_db()
    assert application.status == "REJECTED"
    assert ApplicationStatusHistory.objects.filter(application=application).count() == 2


def test_repeating_a_move_that_worked_changes_nothing(api_as):
    application = make_application()
    client = api_as(application.opportunity.creator)
    assert move(client, application, "SCREENING", expected="APPLIED").status_code == 200

    # The same request again, as after a timeout the client never saw the answer to.
    again = move(client, application, "SCREENING", expected="APPLIED")

    assert again.status_code == 200
    assert again.json()["status"] == "SCREENING"
    assert ApplicationStatusHistory.objects.filter(to_status="SCREENING").count() == 1
    assert Notification.objects.count() == 1


def test_who_may_move_an_application(api, api_as):
    job, people = organization_job()
    application = make_application(opportunity=job)

    assert move(api_as(application.applicant), application, "HIRED").status_code == 403
    for outsider in (people["MEMBER"], UserFactory(), UserFactory(platform_role="ADMIN")):
        assert move(api_as(outsider), application, "HIRED").status_code == 404
    assert move(api, application, "HIRED").status_code == 401
    application.refresh_from_db()
    assert application.status == "APPLIED"

    for role, to in (("OWNER", "SCREENING"), ("ADMIN", "SHORTLISTED"), ("RECRUITER", "INTERVIEW")):
        application.refresh_from_db()
        assert move(api_as(people[role]), application, to).status_code == 200


def test_someone_who_joins_the_hiring_team_cannot_decide_their_own_application(api_as):
    job, people = organization_job()
    application = make_application(opportunity=job)
    ApplicationStatusHistory.objects.filter(application=application).update(note="Internal note.")
    MemberFactory(organization=job.organization, user=application.applicant, role="RECRUITER")
    client = api_as(application.applicant)

    assert move(client, application, "HIRED").status_code == 403

    detail = client.get(f"/api/v1/applications/{application.pk}/").json()
    assert detail["viewer"]["can_manage"] is False
    assert detail["viewer"]["next_statuses"] == []
    assert "Internal note." not in str(detail)
    # In the pipeline they now help run, their own row offers no moves.
    (row,) = client.get(pipeline_url(job)).json()["results"]
    assert row["next_statuses"] == []
    # Their colleagues are unaffected.
    assert move(api_as(people["OWNER"]), application, "SCREENING").status_code == 200


def test_the_request_is_validated(api_as):
    application = make_application()
    client = api_as(application.opportunity.creator)
    url = move_url(application)

    def errors_for(body):
        response = client.post(url, body)
        assert response.status_code == 400, response.content
        return set(response.json()["errors"])

    assert errors_for({}) == {"to", "expected_status"}
    # Withdrawing is the applicant's own action, and "applied" is where everyone starts.
    for to in ("WITHDRAWN", "APPLIED", "MAYBE"):
        assert errors_for({"to": to, "expected_status": "APPLIED"}) == {"to"}
    assert errors_for({"to": "HIRED", "expected_status": "APPLIED", "note": "x" * 501}) == {"note"}

    with pytest.raises(InvalidTransition):
        services.transition(
            user=application.opportunity.creator, application_id=application.pk, to=S.WITHDRAWN
        )


def test_an_applicant_who_turned_these_off_is_not_told(api_as):
    application = make_application()
    notifications.set_preferences(
        user=application.applicant, choices={Category.APPLICATIONS: (False, False)}
    )

    assert move(api_as(application.opportunity.creator), application, "OFFER").status_code == 200

    assert not Notification.objects.exists() and mail.outbox == []


def test_the_applicants_open_pages_are_told_live(
    api_as, monkeypatch, django_capture_on_commit_callbacks
):
    published = []
    monkeypatch.setattr(events, "publish", lambda *args: published.append(args))
    application = make_application()

    with django_capture_on_commit_callbacks(execute=True):
        # Nothing is pushed for a move that is refused.
        assert move(api_as(UserFactory()), application, "OFFER").status_code == 404
    assert published == []

    with django_capture_on_commit_callbacks(execute=True):
        move(api_as(application.opportunity.creator), application, "OFFER")

    updates = [event for event in published if event[1] == "application.updated"]
    assert updates == [
        (
            str(application.applicant.pk),
            "application.updated",
            {"id": str(application.pk), "status": "OFFER"},
        )
    ]


# --- Races ------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_recruiters_deciding_at_once_one_wins_and_the_other_is_told():
    job, people = organization_job()
    application = make_application(opportunity=job)

    def decide(user, to):
        return lambda: services.transition(
            user=user, application_id=application.pk, to=to, expected=S.APPLIED
        )

    outcomes = run_together(
        decide(people["ADMIN"], S.INTERVIEW), decide(people["RECRUITER"], S.REJECTED)
    )

    (lost,) = errors(outcomes)
    assert isinstance(lost, StaleState)
    application.refresh_from_db()
    assert application.status in ("INTERVIEW", "REJECTED")
    assert ApplicationStatusHistory.objects.filter(application=application).count() == 2
    assert AuditLog.objects.filter(action="application.status_changed").count() == 1
    assert Notification.objects.filter(recipient=application.applicant).count() == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_a_withdrawal_and_a_decision_at_once_do_not_both_happen():
    application = make_application()
    manager = application.opportunity.creator

    outcomes = run_together(
        lambda: services.withdraw(user=application.applicant, application_id=application.pk),
        lambda: services.transition(
            user=manager, application_id=application.pk, to=S.HIRED, expected=S.APPLIED
        ),
    )

    application.refresh_from_db()
    assert len(errors(outcomes)) == 1
    assert isinstance(errors(outcomes)[0], (StaleState, InvalidTransition))
    assert application.status in ("WITHDRAWN", "HIRED")
    assert ApplicationStatusHistory.objects.filter(application=application).count() == 2
