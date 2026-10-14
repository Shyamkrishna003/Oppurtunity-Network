"""What moderators can do to people, organizations and communities."""

from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.utils import timezone

from audit.models import AuditLog
from communities.tests.factories import community_with_roles
from conftest import SAME_ORIGIN
from moderation.models import ModerationAction, Report
from notifications.models import Notification
from opportunities.tests.factories import make_job
from organizations.tests.factories import organization_with_roles
from realtime import tickets
from realtime.consumers import StreamConsumer
from users.models import RefreshToken, User
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

ACTIONS = "/api/v1/moderation/actions/"
QUEUE = "/api/v1/moderation/reports/"
PASSWORD = "correct-horse-battery"


def moderator():
    return UserFactory(platform_role="MODERATOR")


def admin():
    return UserFactory(platform_role="ADMIN")


def act(client, target, kind, action, reason="For the record.", **extra):
    return client.post(
        ACTIONS,
        {
            "target_type": kind,
            "target_id": str(target.pk),
            "action": action,
            "reason": reason,
            **extra,
        },
    )


def target_view(client, target, kind):
    return client.get(f"/api/v1/moderation/targets/{kind}/{target.pk}/").json()


def in_days(days):
    return (timezone.now() + timedelta(days=days)).isoformat()


# --- People -----------------------------------------------------------------------------


def test_a_warning_tells_the_person_and_changes_nothing_else(api_as):
    person, staff = UserFactory(), moderator()

    response = act(api_as(staff), person, "USER", "WARN", "Stop sending the same message.")

    assert response.status_code == 201
    person.refresh_from_db()
    assert not person.is_suspended and not person.is_posting_restricted
    notice = Notification.objects.get()
    assert (notice.recipient, notice.type, notice.actor) == (person, "ACCOUNT_MODERATED", None)
    listed = api_as(person).get("/api/v1/notifications/").json()["results"][0]
    assert listed["title"] == "A moderator has sent you a warning"
    assert "Stop sending the same message." in listed["body"]
    # They are not told which moderator.
    assert str(staff.pk) not in str(listed)
    log = AuditLog.objects.get(action="moderation.action_taken")
    assert (log.actor, log.target_id, log.metadata["action"]) == (staff, person.pk, "WARN")


def test_a_posting_restriction_stops_new_posts_and_nothing_else(api_as):
    person = UserFactory()
    draft = make_job(creator=person)
    published = make_job(status="PUBLISHED", creator=person)
    community, _ = community_with_roles()
    client, staff = api_as(person), api_as(moderator())

    restricted = act(staff, person, "USER", "RESTRICT_POSTING", "Spam.", until=in_days(7))
    assert restricted.status_code == 201
    assert restricted.json()["expires_at"] is not None

    create = client.post("/api/v1/opportunities/", {"type": "JOB", "title": "Another"})
    publish = client.post(f"/api/v1/opportunities/{draft.pk}/publish/")
    share = client.post(
        f"/api/v1/opportunities/{published.pk}/communities/",
        {"community_ids": [str(community.pk)]},
    )
    for response in (create, publish, share):
        assert (response.status_code, response.json()["code"]) == (403, "posting_restricted")
    # Everything else still works: they can read, edit what is up, and close it.
    assert client.get("/api/v1/opportunities/").status_code == 200
    assert (
        client.patch(
            f"/api/v1/opportunities/{published.pk}/", {"description": "Clarified."}
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/opportunities/{published.pk}/close/", {"reason": "OTHER"}).status_code
        == 200
    )
    assert target_view(staff, person, "USER")["standing"][0].startswith("Cannot post until ")

    # Lifted by a moderator, and they are told both times.
    assert act(staff, person, "USER", "UNRESTRICT_POSTING", "Appeal accepted.").status_code == 201
    assert client.post(f"/api/v1/opportunities/{draft.pk}/publish/").status_code == 200
    titles = [n["title"] for n in client.get("/api/v1/notifications/").json()["results"]]
    assert titles == ["You can post again", "You cannot post for now"]


def test_a_restriction_lapses_by_itself():
    person = UserFactory()
    User.objects.filter(pk=person.pk).update(
        posting_restricted_until=timezone.now() - timedelta(seconds=1),
        suspended_until=timezone.now() - timedelta(seconds=1),
    )
    person.refresh_from_db()

    assert not person.is_posting_restricted and not person.is_suspended


def test_suspending_someone_signs_them_out_everywhere_at_once(api, api_as):
    person = UserFactory()
    login = api.post("/api/v1/auth/login/", {"email": person.email, "password": PASSWORD})
    access = login.json()["access_token"]
    bearer = {"HTTP_AUTHORIZATION": f"Bearer {access}"}
    assert api.get("/api/v1/users/me/", **bearer).status_code == 200
    ticket = tickets.issue(person)

    response = act(api_as(admin()), person, "USER", "SUSPEND", "Fraud.", until=in_days(30))

    assert response.status_code == 201
    # The access token they already hold stops working, whatever is left on its clock.
    refused = api.get("/api/v1/users/me/", **bearer)
    assert (refused.status_code, refused.json()["code"]) == (403, "account_suspended")
    # The refresh cookie cannot make a new one, and every session is revoked.
    assert api.post("/api/v1/auth/refresh/", headers=SAME_ORIGIN).status_code == 401
    assert not RefreshToken.objects.filter(user=person, revoked_at__isnull=True).exists()
    # Signing in again is refused, and says why only to someone with the right password.
    again = api.post("/api/v1/auth/login/", {"email": person.email, "password": PASSWORD})
    assert (again.status_code, again.json()["code"]) == (403, "account_suspended")
    wrong = api.post("/api/v1/auth/login/", {"email": person.email, "password": "wrong-password"})
    assert (wrong.status_code, wrong.json()["code"]) == (401, "invalid_credentials")

    # A socket ticket issued a moment before is no use either.
    async def connect():
        socket = WebsocketCommunicator(StreamConsumer.as_asgi(), f"/ws/stream/?ticket={ticket}")
        await socket.connect()
        message = await socket.receive_output(timeout=2)
        return message["type"], message.get("code")

    assert async_to_sync(connect)() == ("websocket.close", 4401)

    # They are told by email, since they cannot sign in to read it.
    notice = Notification.objects.get(recipient=person)
    assert notice.type == "ACCOUNT_MODERATED" and notice.payload["action"] == "SUSPEND"
    assert notice.deliveries.filter(channel="EMAIL").exists()


def test_lifting_a_suspension_lets_them_back_in(api, api_as):
    person, boss = UserFactory(), api_as(admin())
    act(boss, person, "USER", "SUSPEND", "Fraud.")
    assert target_view(boss, person, "USER")["standing"] == ["Suspended until lifted"]
    assert target_view(boss, person, "USER")["possible_actions"] == [
        "RESTRICT_POSTING",
        "UNSUSPEND",
        "WARN",
    ]

    assert act(boss, person, "USER", "UNSUSPEND", "Mistaken identity.").status_code == 201

    login = api.post("/api/v1/auth/login/", {"email": person.email, "password": PASSWORD})
    assert login.status_code == 200
    assert [a.action_type for a in ModerationAction.objects.order_by("created_at")] == [
        "SUSPEND",
        "UNSUSPEND",
    ]


def test_who_may_do_what_to_whom(api_as):
    person, staff, colleague, boss = UserFactory(), moderator(), moderator(), admin()

    # Suspending is for admins.
    refused = act(api_as(staff), person, "USER", "SUSPEND")
    assert refused.status_code == 403
    assert act(api_as(boss), person, "USER", "SUSPEND").status_code == 201
    assert act(api_as(staff), person, "USER", "UNSUSPEND").status_code == 403
    # Nobody moderates themselves; a moderator does not moderate other staff; an admin can.
    for actor, target in ((staff, staff), (staff, colleague), (staff, boss), (boss, boss)):
        response = act(api_as(actor), target, "USER", "WARN")
        assert response.status_code == 403, (actor.platform_role, target.platform_role)
        assert target_view(api_as(actor), target, "USER")["possible_actions"] == []
    assert act(api_as(boss), staff, "USER", "WARN").status_code == 201
    # And none of it is open to anyone else.
    assert act(api_as(person), staff, "USER", "WARN").status_code == 403
    assert (
        api_as(UserFactory()).get(f"/api/v1/moderation/targets/USER/{person.pk}/").status_code
        == 403
    )
    person.refresh_from_db()
    assert person.is_suspended


@pytest.mark.parametrize(
    ("action", "extra", "status", "code"),
    [
        ("SUSPEND", {"until": "2020-01-01T00:00:00Z"}, 422, "invalid_until"),
        ("WARN", {"until": (timezone.now() + timedelta(days=1)).isoformat()}, 422, "invalid_until"),
        ("SUSPEND", {"until": "soon"}, 400, "validation_error"),
        ("UNSUSPEND", {}, 409, "action_not_possible"),  # not suspended
        ("UNRESTRICT_POSTING", {}, 409, "action_not_possible"),
        ("VERIFY", {}, 422, "action_unavailable"),  # not something done to a person
    ],
)
def test_actions_on_a_person_are_checked(api_as, action, extra, status, code):
    person = UserFactory()

    response = act(api_as(admin()), person, "USER", action, **extra)

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert not ModerationAction.objects.exists() and not Notification.objects.exists()


def test_nothing_is_done_twice(api_as):
    person, boss = UserFactory(), api_as(admin())
    assert act(boss, person, "USER", "SUSPEND").status_code == 201

    again = act(boss, person, "USER", "SUSPEND")

    assert (again.status_code, again.json()["code"]) == (409, "action_not_possible")
    assert ModerationAction.objects.count() == 1


def test_acting_on_a_reported_person_settles_the_reports_about_them(api_as):
    person, staff = UserFactory(), moderator()
    first = Report.objects.create(
        reporter=UserFactory(), target_type="USER", target_user=person, category="HARASSMENT"
    )
    second = Report.objects.create(
        reporter=UserFactory(), target_type="USER", target_user=person, category="SPAM"
    )

    response = api_as(staff).post(
        f"{QUEUE}{first.pk}/resolve/",
        {"action": "RESTRICT_POSTING", "reason": "Repeated spam.", "until": in_days(3)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ACTION_TAKEN"
    assert response.json()["actions"][0]["action_type"] == "RESTRICT_POSTING"
    second.refresh_from_db()
    assert second.status == "ACTION_TAKEN"
    # The reporters hear that it was reviewed; only the person hears what was done.
    assert {(n.recipient_id, n.type) for n in Notification.objects.all()} == {
        (first.reporter_id, "REPORT_REVIEWED"),
        (second.reporter_id, "REPORT_REVIEWED"),
        (person.pk, "ACCOUNT_MODERATED"),
    }
    # Lifting a restriction is not an answer to a report.
    third = Report.objects.create(
        reporter=UserFactory(), target_type="USER", target_user=person, category="SPAM"
    )
    wrong = api_as(staff).post(
        f"{QUEUE}{third.pk}/resolve/", {"action": "UNRESTRICT_POSTING", "reason": "x"}
    )
    assert (wrong.status_code, wrong.json()["code"]) == (422, "action_unavailable")


# --- Organizations and communities ------------------------------------------------------


def test_verifying_an_organization_is_for_admins_and_shows_on_its_page(api, api_as):
    organization, members = organization_with_roles("ADMIN")
    url = f"/api/v1/organizations/{organization.pk}/"

    assert act(api_as(moderator()), organization, "ORGANIZATION", "VERIFY").status_code == 403
    assert api.get(url).json()["verification_status"] == "UNVERIFIED"
    boss = api_as(admin())
    assert (
        act(boss, organization, "ORGANIZATION", "VERIFY", "Documents checked.").status_code == 201
    )

    assert api.get(url).json()["verification_status"] == "VERIFIED"
    assert target_view(boss, organization, "ORGANIZATION")["standing"] == ["Verified"]
    # Its owners are told; its other members are not.
    notice = Notification.objects.get()
    assert (notice.recipient, notice.type) == (members["OWNER"].user, "ORGANIZATION_MODERATED")
    listed = api_as(members["OWNER"].user).get("/api/v1/notifications/").json()["results"][0]
    assert listed["title"] == f"{organization.name} is now verified"
    assert listed["url"] == f"/organizations/{organization.pk}"
    log = AuditLog.objects.get(action="moderation.action_taken")
    assert log.organization_id == organization.pk

    assert act(boss, organization, "ORGANIZATION", "VERIFY").json()["code"] == "action_not_possible"
    assert act(boss, organization, "ORGANIZATION", "UNVERIFY", "Lapsed.").status_code == 201
    assert api.get(url).json()["verification_status"] == "UNVERIFIED"


def test_a_suspended_organization_cannot_post(api_as):
    organization, members = organization_with_roles("RECRUITER")
    recruiter = api_as(members["RECRUITER"].user)
    draft = make_job(organization=organization, creator=members["RECRUITER"].user)
    boss = api_as(admin())

    assert (
        act(boss, organization, "ORGANIZATION", "SUSPEND", "Fraudulent listings.").status_code
        == 201
    )

    created = recruiter.post(
        "/api/v1/opportunities/",
        {"type": "JOB", "title": "New role", "organization_id": str(organization.pk)},
    )
    published = recruiter.post(f"/api/v1/opportunities/{draft.pk}/publish/")
    for response in (created, published):
        assert (response.status_code, response.json()["code"]) == (422, "organization_suspended")

    assert act(boss, organization, "ORGANIZATION", "UNSUSPEND", "Resolved.").status_code == 201
    assert recruiter.post(f"/api/v1/opportunities/{draft.pk}/publish/").status_code == 200


def test_suspending_a_community_tells_its_owners_and_stops_sharing_into_it(api_as):
    community, members = community_with_roles("MEMBER")
    member = members["MEMBER"].user
    job = make_job(status="PUBLISHED", creator=member)
    boss = api_as(admin())

    assert act(api_as(moderator()), community, "COMMUNITY", "SUSPEND").status_code == 403
    assert act(boss, community, "COMMUNITY", "SUSPEND", "Scam recruitment.").status_code == 201

    notice = Notification.objects.get()
    assert (notice.recipient, notice.type) == (members["OWNER"].user, "COMMUNITY_MODERATED")
    assert target_view(boss, community, "COMMUNITY")["standing"] == ["Suspended"]
    shared = api_as(member).post(
        f"/api/v1/opportunities/{job.pk}/communities/", {"community_ids": [str(community.pk)]}
    )
    assert shared.status_code == 422
    assert AuditLog.objects.get(action="moderation.action_taken").community_id == community.pk

    assert act(boss, community, "COMMUNITY", "UNSUSPEND", "New owners.").status_code == 201
    assert target_view(boss, community, "COMMUNITY")["standing"] == []


# --- The moderators' view of a target ---------------------------------------------------


def test_a_moderator_can_open_anything_with_its_history(api_as):
    job, staff = make_job(status="PUBLISHED", title="Easy money"), api_as(moderator())
    act(staff, job, "OPPORTUNITY", "HIDE", "Scam.")

    view = target_view(staff, job, "OPPORTUNITY")

    assert view["target"] == {
        "type": "OPPORTUNITY",
        "id": str(job.pk),
        "name": "Easy money",
        "url": f"/opportunities/{job.pk}",
    }
    assert view["standing"] == ["Hidden"]
    assert view["possible_actions"] == ["REMOVE", "RESTORE"]
    assert view["timed_actions"] == []
    assert [(a["action_type"], a["reason"]) for a in view["actions"]] == [("HIDE", "Scam.")]
    # Which actions take an end time is said, so the form knows when to ask for one.
    person = UserFactory()
    assert target_view(api_as(admin()), person, "USER")["timed_actions"] == [
        "RESTRICT_POSTING",
        "SUSPEND",
    ]
    assert staff.get(f"/api/v1/moderation/targets/MESSAGE/{job.pk}/").status_code == 404
    assert staff.get(f"/api/v1/moderation/targets/USER/{job.pk}/").status_code == 404
