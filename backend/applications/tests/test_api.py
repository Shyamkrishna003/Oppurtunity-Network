from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from applications.models import Application, ApplicationStatusHistory
from applications.tests.factories import PDF, make_application, pdf
from audit.models import AuditLog
from common.throttles import ScopedThrottle
from notifications.models import Notification
from opportunities.models import Opportunity
from opportunities.tests.factories import make_job
from organizations.tests.factories import organization_with_roles
from users.models import UserBlock
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPLICATIONS = "/api/v1/applications/"


def apply_url(opportunity) -> str:
    return f"/api/v1/jobs/{opportunity.pk}/apply/"


def send(client, opportunity, **body):
    body.setdefault("resume", pdf())
    return client.post(apply_url(opportunity), body, format="multipart")


def stored_files(settings) -> list[Path]:
    root = Path(settings.PRIVATE_MEDIA_ROOT)
    return [path for path in root.rglob("*") if path.is_file()]


def organization_job(**fields):
    organization, members = organization_with_roles("ADMIN", "RECRUITER", "MEMBER")
    job = make_job(
        status="PUBLISHED", organization=organization, creator=members["RECRUITER"].user, **fields
    )
    return job, {role: member.user for role, member in members.items()}


# --- Applying ---------------------------------------------------------------------------


def test_applying_creates_the_application_and_tells_the_people_who_manage_the_job(api_as, settings):
    job, people = organization_job(title="Backend Engineer")
    applicant = UserFactory()
    applicant.profile.headline = "Python developer"
    applicant.profile.save()

    response = send(api_as(applicant), job, cover_note="I have run Django in production.")

    assert response.status_code == 201
    body = response.json()
    application = Application.objects.get()
    assert body["id"] == str(application.pk)
    assert (body["status"], body["cover_note"]) == (
        "APPLIED",
        "I have run Django in production.",
    )
    assert body["opportunity"]["title"] == "Backend Engineer"
    assert body["applicant"]["id"] == str(applicant.pk)
    assert body["headline"] == "Python developer"
    assert body["history"] == [
        {"from_status": "", "to_status": "APPLIED", "created_at": body["history"][0]["created_at"]}
    ]
    assert body["viewer"] == {
        "is_applicant": True,
        "can_manage": False,
        "can_withdraw": True,
        "can_download_resume": True,
    }
    # The storage key is not part of any response.
    assert "resume" not in body and application.resume not in response.content.decode()

    # Stored privately, under a name that owes nothing to the upload.
    (stored,) = stored_files(settings)
    assert stored.read_bytes() == PDF
    assert application.resume.startswith("resumes/") and "resume.pdf" not in application.resume
    assert not Path(settings.MEDIA_ROOT).exists()

    log = AuditLog.objects.get(action="application.submitted")
    assert (log.actor, log.target_id, log.organization_id) == (
        applicant,
        application.pk,
        job.organization_id,
    )
    # Owners, admins and recruiters handle applications; ordinary members do not.
    told = Notification.objects.filter(type="APPLICATION_RECEIVED")
    assert {n.recipient for n in told} == {people["OWNER"], people["ADMIN"], people["RECRUITER"]}
    assert told[0].payload["application_id"] == str(application.pk)


def test_a_personal_job_tells_its_poster(api_as):
    poster = UserFactory()
    job = make_job(status="PUBLISHED", creator=poster)

    assert send(api_as(UserFactory()), job).status_code == 201

    assert Notification.objects.get().recipient == poster


def test_applying_again_returns_the_application_that_exists(api_as, settings):
    job = make_job(status="PUBLISHED")
    client = api_as(UserFactory())
    first = send(client, job, cover_note="First.")

    second = send(client, job, cover_note="Second.")

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["cover_note"] == "First."
    assert Application.objects.count() == 1
    assert len(stored_files(settings)) == 1
    assert Notification.objects.count() == 1
    assert AuditLog.objects.filter(action="application.submitted").count() == 1


def test_a_withdrawn_application_is_not_replaced_by_applying_again(api_as):
    application = make_application(status="WITHDRAWN")

    response = send(api_as(application.applicant), application.opportunity)

    assert response.status_code == 200
    assert response.json()["status"] == "WITHDRAWN"
    assert Application.objects.count() == 1


def test_an_account_must_be_signed_in_and_verified_to_apply(api, api_as):
    job = make_job(status="PUBLISHED")

    assert send(api, job).status_code == 401
    unverified = send(api_as(UserFactory(unverified=True)), job)
    assert (unverified.status_code, unverified.json()["code"]) == (403, "email_not_verified")
    assert not Application.objects.exists()


def test_a_job_the_caller_cannot_see_does_not_exist_for_them(api_as):
    organization, _ = organization_with_roles()
    outsider = api_as(UserFactory())
    hidden = [
        make_job(status="DRAFT"),
        make_job(status="ARCHIVED"),
        make_job(status="PUBLISHED", moderation_status="HIDDEN"),
        make_job(status="PUBLISHED", organization=organization, visibility="ORGANIZATION"),
    ]
    event = Opportunity.objects.create(
        type="EVENT",
        status="PUBLISHED",
        published_at=timezone.now(),
        creator=UserFactory(),
        title="Meetup",
    )

    for opportunity in (*hidden, event):
        assert send(outsider, opportunity).status_code == 404
    assert (
        outsider.post(
            "/api/v1/jobs/0199b7c0-0000-7000-8000-000000000000/apply/", {}, format="multipart"
        ).status_code
        == 404
    )
    assert not Application.objects.exists()


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "CLOSED"},
        {"status": "EXPIRED"},
        {"status": "PUBLISHED", "deadline": timezone.now() - timedelta(minutes=1)},
    ],
)
def test_a_job_that_is_no_longer_open_refuses_applications(api_as, settings, fields):
    response = send(api_as(UserFactory()), make_job(**fields))

    assert (response.status_code, response.json()["code"]) == (409, "not_accepting")
    assert not Application.objects.exists() and stored_files(settings) == []


def test_reasons_a_visible_open_job_cannot_be_applied_to(api_as):
    job, people = organization_job()
    personal = make_job(status="PUBLISHED")
    external = make_job(
        status="PUBLISHED",
        job={"application_method": "EXTERNAL", "external_url": "https://example.com/apply"},
    )
    blocked, blocking = UserFactory(), make_job(status="PUBLISHED")
    UserBlock.objects.create(blocker=blocking.creator, blocked=blocked)

    def code(user, opportunity):
        response = send(api_as(user), opportunity)
        return response.status_code, response.json()["code"]

    for role in ("OWNER", "ADMIN", "RECRUITER"):
        assert code(people[role], job) == (422, "own_job")
    assert code(personal.creator, personal) == (422, "own_job")
    assert code(UserFactory(), external) == (422, "external_application")
    # Indistinguishable from a closed job, so the block is not revealed.
    assert code(blocked, blocking) == (409, "not_accepting")
    assert not Application.objects.exists()

    # An ordinary member of the organization does not manage its jobs, and may apply.
    assert send(api_as(people["MEMBER"]), job).status_code == 201


def test_the_resume_is_judged_by_its_content(api_as, settings):
    job = make_job(status="PUBLISHED")
    client = api_as(UserFactory())
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    def code(**body):
        response = client.post(apply_url(job), body, format="multipart")
        assert response.status_code == 422, response.content
        assert "resume" in response.json()["errors"]
        return response.json()["code"]

    assert code() == "file_required"
    assert code(resume=pdf(content=png)) == "invalid_file"
    assert code(resume=pdf(content=b"<script>alert(1)</script> %PDF-1.7")) == "invalid_file"
    settings.RESUME_MAX_BYTES = len(PDF) - 1
    assert code(resume=pdf()) == "file_too_large"
    assert not Application.objects.exists() and stored_files(settings) == []

    # A real PDF is accepted whatever the client calls it.
    settings.RESUME_MAX_BYTES = len(PDF)
    odd = pdf(name="../../evil.exe", content_type="application/x-msdownload")
    assert send(client, job, resume=odd).status_code == 201
    (stored,) = stored_files(settings)
    assert stored.suffix == ".pdf" and stored.parent.name == "resumes"


def test_the_request_itself_is_validated(api_as):
    job = make_job(status="PUBLISHED")
    client = api_as(UserFactory())

    too_long = send(client, job, cover_note="x" * 4001)
    assert (too_long.status_code, list(too_long.json()["errors"])) == (400, ["cover_note"])
    assert client.post(apply_url(job), {"cover_note": "hi"}, format="json").status_code == 415
    assert not Application.objects.exists()


def test_applying_is_rate_limited(api_as, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "application_create", "2/day")
    client = api_as(UserFactory())

    codes = [send(client, make_job(status="PUBLISHED")).status_code for _ in range(3)]

    assert codes == [201, 201, 429]


def test_the_job_page_says_whether_the_viewer_can_apply_or_already_has(api, api_as):
    job = make_job(status="PUBLISHED")
    applicant = UserFactory()
    url = f"/api/v1/opportunities/{job.pk}/"

    def viewer(client):
        data = client.get(url).json()["viewer"]
        return data["can_apply"], data["application"]

    assert viewer(api) == (False, None)
    assert viewer(api_as(job.creator)) == (False, None)
    assert viewer(api_as(UserFactory(unverified=True))) == (True, None)  # asked to verify on trying
    assert viewer(api_as(applicant)) == (True, None)

    application_id = send(api_as(applicant), job).json()["id"]

    assert viewer(api_as(applicant)) == (False, {"id": application_id, "status": "APPLIED"})
    assert viewer(api_as(UserFactory())) == (True, None)

    closed = make_job(status="CLOSED")
    assert api_as(applicant).get(f"/api/v1/opportunities/{closed.pk}/").json()["viewer"][
        "can_apply"
    ] is (False)


# --- My applications --------------------------------------------------------------------


def test_my_applications_lists_only_mine_newest_first(api_as, django_assert_max_num_queries):
    me = UserFactory()
    job, _ = organization_job(title="Platform Engineer")
    older = make_application(applicant=me, status="REJECTED")
    newer = make_application(applicant=me, opportunity=job)
    make_application()  # someone else's
    make_application(opportunity=job)  # someone else's, to the same job
    client = api_as(me)

    response = client.get(APPLICATIONS)

    assert response.status_code == 200
    results = response.json()["results"]
    assert [row["id"] for row in results] == [str(newer.pk), str(older.pk)]
    assert results[0]["opportunity"] == {
        "id": str(job.pk),
        "title": "Platform Engineer",
        "status": "PUBLISHED",
        "organization": {
            "id": str(job.organization.pk),
            "name": job.organization.name,
            "slug": job.organization.slug,
            "verification_status": job.organization.verification_status,
        },
    }
    assert set(results[0]) == {"id", "status", "created_at", "status_changed_at", "opportunity"}

    for _ in range(6):
        make_application(applicant=me)
    with django_assert_max_num_queries(3):
        assert len(client.get(APPLICATIONS).json()["results"]) == 8


def test_my_applications_can_be_filtered_by_status(api, api_as):
    me = UserFactory()
    make_application(applicant=me)
    rejected = make_application(applicant=me, status="REJECTED")
    client = api_as(me)

    only = client.get(APPLICATIONS, {"status": "REJECTED"}).json()["results"]

    assert [row["id"] for row in only] == [str(rejected.pk)]
    assert client.get(APPLICATIONS, {"status": "HIRED"}).json()["results"] == []
    assert client.get(APPLICATIONS, {"status": "nonsense"}).status_code == 400
    assert api.get(APPLICATIONS).status_code == 401


def test_a_job_that_was_archived_since_still_appears_in_my_applications(api_as):
    application = make_application(opportunity=make_job(status="ARCHIVED"))

    (row,) = api_as(application.applicant).get(APPLICATIONS).json()["results"]

    assert row["opportunity"]["status"] == "ARCHIVED"


# --- One application --------------------------------------------------------------------


def test_who_can_open_an_application(api, api_as):
    job, people = organization_job()
    application = make_application(opportunity=job, cover_note="Hello.")
    url = f"{APPLICATIONS}{application.pk}/"

    mine = api_as(application.applicant).get(url)
    assert mine.status_code == 200
    assert mine.json()["viewer"]["is_applicant"] is True

    for role in ("OWNER", "ADMIN", "RECRUITER"):
        theirs = api_as(people[role]).get(url)
        assert theirs.status_code == 200
        assert theirs.json()["cover_note"] == "Hello."
        assert theirs.json()["viewer"] == {
            "is_applicant": False,
            "can_manage": True,
            "can_withdraw": False,
            "can_download_resume": True,
        }

    # Not the organization's ordinary members, not other applicants, not even platform staff.
    other_applicant = make_application(opportunity=job).applicant
    staff = UserFactory(platform_role="ADMIN")
    for outsider in (people["MEMBER"], other_applicant, UserFactory(), staff):
        assert api_as(outsider).get(url).status_code == 404
    assert api.get(url).status_code == 401


def test_someone_who_leaves_the_organization_loses_its_applications(api_as):
    job, people = organization_job()
    application = make_application(opportunity=job)
    url = f"{APPLICATIONS}{application.pk}/"
    recruiter = api_as(people["RECRUITER"])
    assert recruiter.get(url).status_code == 200

    job.organization.memberships.filter(user=people["RECRUITER"]).update(status="REMOVED")

    assert recruiter.get(url).status_code == 404
    assert recruiter.get(f"{url}resume/").status_code == 404


def test_the_history_never_carries_a_managers_note(api_as):
    application = make_application(status="INTERVIEW")
    ApplicationStatusHistory.objects.filter(to_status="INTERVIEW").update(note="Strong on SQL.")

    response = api_as(application.applicant).get(f"{APPLICATIONS}{application.pk}/")

    assert [step["to_status"] for step in response.json()["history"]] == ["APPLIED", "INTERVIEW"]
    assert "Strong on SQL." not in response.content.decode()


# --- Withdrawing ------------------------------------------------------------------------


def test_the_applicant_can_withdraw_and_the_managers_are_told(api_as):
    job, people = organization_job()
    application = make_application(opportunity=job, status="INTERVIEW")
    client = api_as(application.applicant)
    url = f"{APPLICATIONS}{application.pk}/withdraw/"

    response = client.post(url)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "WITHDRAWN"
    assert body["viewer"]["can_withdraw"] is False
    assert (body["history"][-1]["from_status"], body["history"][-1]["to_status"]) == (
        "INTERVIEW",
        "WITHDRAWN",
    )
    log = AuditLog.objects.get(action="application.withdrawn")
    assert (log.actor, log.metadata) == (application.applicant, {"from": "INTERVIEW"})
    told = Notification.objects.filter(type="APPLICATION_WITHDRAWN")
    assert {n.recipient for n in told} == {people["OWNER"], people["ADMIN"], people["RECRUITER"]}

    # Twice is the same as once.
    assert client.post(url).status_code == 200
    assert ApplicationStatusHistory.objects.filter(to_status="WITHDRAWN").count() == 1
    assert Notification.objects.filter(type="APPLICATION_WITHDRAWN").count() == 3


def test_only_the_applicant_withdraws(api_as):
    job, people = organization_job()
    application = make_application(opportunity=job)
    url = f"{APPLICATIONS}{application.pk}/withdraw/"

    assert api_as(people["RECRUITER"]).post(url).status_code == 403
    assert api_as(UserFactory()).post(url).status_code == 404
    application.refresh_from_db()
    assert application.status == "APPLIED"


@pytest.mark.parametrize("status", ["HIRED", "REJECTED"])
def test_a_decided_application_cannot_be_withdrawn(api_as, status):
    application = make_application(status=status)

    response = api_as(application.applicant).post(f"{APPLICATIONS}{application.pk}/withdraw/")

    assert (response.status_code, response.json()["code"]) == (409, "invalid_transition")


# --- The resume -------------------------------------------------------------------------


def test_the_resume_is_downloaded_through_a_link_that_needs_no_token(api, api_as):
    applicant = UserFactory()
    applicant.profile.display_name = "Ada Lovelace"
    applicant.profile.save()
    application = make_application(applicant=applicant)

    link = api_as(applicant).get(f"{APPLICATIONS}{application.pk}/resume/")

    assert link.status_code == 200
    assert link.json()["expires_in"] == 60
    assert application.resume not in link.json()["url"]  # the key is inside the signed part
    download = api.get(link.json()["url"])
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == PDF
    assert download["Content-Type"] == "application/pdf"
    assert download["Content-Disposition"] == 'attachment; filename="resume-ada-lovelace.pdf"'
    assert download["Cache-Control"] == "private, no-store"
    assert "sandbox" in download["Content-Security-Policy"]
    assert download["X-Content-Type-Options"] == "nosniff"
    # Looking at your own resume is not an event worth recording.
    assert not AuditLog.objects.filter(action="application.resume_downloaded").exists()


def test_an_employer_taking_a_resume_is_recorded(api_as):
    job, people = organization_job()
    application = make_application(opportunity=job)

    response = api_as(people["RECRUITER"]).get(f"{APPLICATIONS}{application.pk}/resume/")

    assert response.status_code == 200
    log = AuditLog.objects.get(action="application.resume_downloaded")
    assert (log.actor, log.target_id, log.organization_id) == (
        people["RECRUITER"],
        application.pk,
        job.organization_id,
    )


def test_who_cannot_have_the_resume(api, api_as):
    job, people = organization_job()
    application = make_application(opportunity=job)
    withdrawn = make_application(opportunity=job, status="WITHDRAWN")

    for outsider in (people["MEMBER"], UserFactory(), UserFactory(platform_role="ADMIN")):
        assert api_as(outsider).get(f"{APPLICATIONS}{application.pk}/resume/").status_code == 404
    assert api.get(f"{APPLICATIONS}{application.pk}/resume/").status_code == 401
    # Withdrawing takes the resume back from the employer, but not from its owner.
    url = f"{APPLICATIONS}{withdrawn.pk}/resume/"
    assert api_as(people["OWNER"]).get(url).status_code == 403
    assert api_as(withdrawn.applicant).get(url).status_code == 200
    assert not AuditLog.objects.filter(action="application.resume_downloaded").exists()


def test_a_download_link_cannot_be_forged_reused_late_or_outlive_its_file(api, api_as, settings):
    application = make_application()
    client = api_as(application.applicant)
    url = client.get(f"{APPLICATIONS}{application.pk}/resume/").json()["url"]

    assert api.get(url[:-2] + "xx/").status_code == 404
    assert api.get("/api/v1/files/not-a-token/").status_code == 404
    assert api.get("/api/v1/files/not-a-token/").json()["code"] == "not_found"
    # Signing a different file name with no key gets nowhere.
    assert api.get("/api/v1/files/eyJuIjoiLi4vLi4vZXRjL3Bhc3N3ZCJ9:1abc:xyz/").status_code == 404

    settings.PRIVATE_DOWNLOAD_TTL = timedelta(seconds=-1)
    assert api.get(url).status_code == 404

    settings.PRIVATE_DOWNLOAD_TTL = timedelta(seconds=60)
    assert api.get(url).status_code == 200
    (stored,) = stored_files(settings)
    stored.unlink()
    assert api.get(url).status_code == 404
