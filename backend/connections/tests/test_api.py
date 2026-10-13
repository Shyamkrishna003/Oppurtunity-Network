import uuid

import pytest

from common.throttles import ScopedThrottle
from connections.models import Connection
from connections.tests.factories import make_connection
from notifications.models import Notification
from users.models import UserBlock, UserProfile
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

CONNECTIONS = "/api/v1/connections/"
SUMMARY = "/api/v1/connections/summary/"


def one(connection, action="") -> str:
    return f"{CONNECTIONS}{connection.pk}/{action}"


def ask(client, user):
    return client.post(CONNECTIONS, {"user_id": str(user.pk)}, format="json")


def listed(client, state=""):
    response = client.get(CONNECTIONS, {"state": state} if state else {})
    assert response.status_code == 200
    return [(row["user"]["id"], row["state"]) for row in response.json()["results"]]


def profile(client, user):
    return client.get(f"/api/v1/users/{user.pk}/")


# --- Asking -----------------------------------------------------------------------------


def test_asking_creates_a_request_and_tells_the_other_person(api_as):
    alice = UserFactory(display_name="Alice")
    bob = UserFactory(display_name="Bob")

    response = ask(api_as(alice), bob)

    assert response.status_code == 201
    connection = Connection.objects.get()
    assert response.json() == {
        "id": str(connection.pk),
        "state": "OUTGOING",
        "user": {"id": str(bob.pk), "display_name": "Bob", "headline": "", "avatar_url": None},
        "created_at": response.json()["created_at"],
    }
    assert (connection.status, connection.requested_by) == ("REQUESTED", alice)
    assert connection.user_low_id < connection.user_high_id
    assert listed(api_as(alice), "OUTGOING") == [(str(bob.pk), "OUTGOING")]
    assert listed(api_as(bob), "INCOMING") == [(str(alice.pk), "INCOMING")]
    # Not a connection yet, for either of them.
    assert listed(api_as(alice)) == listed(api_as(bob)) == []
    assert api_as(bob).get(SUMMARY).json() == {"incoming": 1}
    assert api_as(alice).get(SUMMARY).json() == {"incoming": 0}

    notification = Notification.objects.get()
    assert (notification.recipient, notification.type, notification.actor) == (
        bob,
        "CONNECTION_REQUESTED",
        alice,
    )
    shown = api_as(bob).get("/api/v1/notifications/").json()["results"][0]
    assert shown["title"] == "Alice wants to connect"
    assert shown["url"] == "/connections?show=requests"


def test_asking_again_returns_the_request_already_out_and_notifies_nobody(api_as):
    alice, bob = UserFactory(), UserFactory()
    first = ask(api_as(alice), bob)

    second = ask(api_as(alice), bob)

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]
    assert Connection.objects.count() == 1
    assert Notification.objects.count() == 1


def test_asking_someone_who_already_asked_you_points_at_their_request(api_as):
    alice, bob = UserFactory(), UserFactory()
    make_connection(alice, bob, "REQUESTED")

    response = ask(api_as(bob), alice)

    assert (response.status_code, response.json()["code"]) == (409, "request_waiting")
    assert Connection.objects.get().requested_by == alice


def test_asking_a_connection_is_refused(api_as):
    alice, bob = UserFactory(), UserFactory()
    make_connection(alice, bob)

    for client, other in ((api_as(alice), bob), (api_as(bob), alice)):
        response = ask(client, other)
        assert (response.status_code, response.json()["code"]) == (409, "already_connected")


def test_who_cannot_be_asked(api, api_as):
    alice = UserFactory()
    blocked_by_me, blocked_me = UserFactory(), UserFactory()
    UserBlock.objects.create(blocker=alice, blocked=blocked_by_me)
    UserBlock.objects.create(blocker=blocked_me, blocked=alice)
    client = api_as(alice)

    own = ask(client, alice)
    gone = [
        ask(client, blocked_by_me),
        ask(client, blocked_me),
        ask(client, UserFactory(is_active=False)),
        client.post(CONNECTIONS, {"user_id": str(uuid.uuid7())}, format="json"),
    ]

    assert (own.status_code, own.json()["code"]) == (422, "cannot_connect_self")
    # A block in either direction looks exactly like someone who does not exist.
    bodies = []
    for response in gone:
        assert response.status_code == 404
        body = response.json()
        body.pop("request_id")
        bodies.append(body)
    assert all(body == bodies[0] for body in bodies)
    assert client.post(CONNECTIONS, {}, format="json").status_code == 400
    assert ask(api, alice).status_code == 401
    assert ask(api_as(UserFactory(unverified=True)), alice).status_code == 403
    assert not Connection.objects.exists()


def test_asking_is_rate_limited(api_as, monkeypatch):
    monkeypatch.setattr(ScopedThrottle, "THROTTLE_RATES", {"connection_request": "2/day"})
    client = api_as(UserFactory())

    statuses = [ask(client, UserFactory()).status_code for _ in range(3)]

    assert statuses == [201, 201, 429]
    # Reading is not counted against the limit.
    assert client.get(CONNECTIONS).status_code == 200


# --- Answering --------------------------------------------------------------------------


def test_accepting_connects_both_and_tells_whoever_asked(api_as):
    alice = UserFactory(display_name="Alice")
    bob = UserFactory(display_name="Bob")
    connection = make_connection(alice, bob, "REQUESTED")

    response = api_as(bob).post(one(connection, "accept/"))
    again = api_as(bob).post(one(connection, "accept/"))

    assert (response.status_code, again.status_code) == (200, 200)
    assert response.json()["state"] == "CONNECTED"
    connection.refresh_from_db()
    assert connection.status == "ACCEPTED" and connection.responded_at is not None
    assert listed(api_as(alice)) == [(str(bob.pk), "CONNECTED")]
    assert listed(api_as(bob)) == [(str(alice.pk), "CONNECTED")]
    assert listed(api_as(bob), "INCOMING") == listed(api_as(alice), "OUTGOING") == []
    # Told once, however many times the button was pressed.
    notification = Notification.objects.get()
    assert (notification.recipient, notification.type) == (alice, "CONNECTION_ACCEPTED")
    shown = api_as(alice).get("/api/v1/notifications/").json()["results"][0]
    assert shown["title"] == "Bob accepted your request to connect"


def test_a_decline_is_never_revealed_to_whoever_asked(api_as):
    alice, bob = UserFactory(), UserFactory()
    connection = make_connection(alice, bob, "REQUESTED")
    before = profile(api_as(alice), bob).json()["connection"]

    response = api_as(bob).post(one(connection, "decline/"))

    assert response.status_code == 204
    assert api_as(bob).post(one(connection, "decline/")).status_code == 404
    connection.refresh_from_db()
    assert connection.status == "DECLINED"
    assert not Notification.objects.exists()
    # For Bob it is gone; he could ask Alice himself.
    assert listed(api_as(bob), "INCOMING") == []
    assert api_as(bob).get(SUMMARY).json() == {"incoming": 0}
    assert profile(api_as(bob), alice).json()["connection"] is None
    # For Alice nothing changed, whichever way she looks or pokes.
    assert listed(api_as(alice), "OUTGOING") == [(str(bob.pk), "OUTGOING")]
    assert profile(api_as(alice), bob).json()["connection"] == before
    asked_again = ask(api_as(alice), bob)
    assert (asked_again.status_code, asked_again.json()["state"]) == (200, "OUTGOING")
    assert api_as(alice).post(one(connection, "accept/")).status_code == 403
    assert api_as(alice).post(one(connection, "decline/")).status_code == 403
    assert not Notification.objects.exists()


def test_whoever_declined_can_ask_later_which_starts_a_new_request(api_as):
    alice, bob = UserFactory(), UserFactory()
    declined = make_connection(alice, bob, "DECLINED")

    response = ask(api_as(bob), alice)

    assert response.status_code == 201
    connection = Connection.objects.get()
    assert connection.pk != declined.pk
    assert (connection.status, connection.requested_by) == ("REQUESTED", bob)
    assert listed(api_as(alice), "INCOMING") == [(str(bob.pk), "INCOMING")]
    assert listed(api_as(alice), "OUTGOING") == []


def test_only_the_person_asked_may_answer(api_as):
    alice, bob, carol = UserFactory(), UserFactory(), UserFactory()
    connection = make_connection(alice, bob, "REQUESTED")

    for action in ("accept/", "decline/"):
        assert api_as(alice).post(one(connection, action)).status_code == 403
        # Somebody else's request does not exist, as far as Carol can tell.
        assert api_as(carol).post(one(connection, action)).status_code == 404
    assert api_as(carol).delete(one(connection)).status_code == 404

    connection.refresh_from_db()
    assert connection.status == "REQUESTED"


def test_an_answer_cannot_be_changed(api_as):
    alice, bob = UserFactory(), UserFactory()
    connection = make_connection(alice, bob)

    response = api_as(bob).post(one(connection, "decline/"))

    assert (response.status_code, response.json()["code"]) == (409, "invalid_transition")
    connection.refresh_from_db()
    assert connection.status == "ACCEPTED"


# --- Removing ---------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["requester", "recipient"])
def test_either_person_can_end_a_connection(api_as, who):
    alice, bob = UserFactory(), UserFactory()
    connection = make_connection(alice, bob)
    people = {"requester": alice, "recipient": bob}

    response = api_as(people[who]).delete(one(connection))

    assert response.status_code == 204
    assert not Connection.objects.exists()
    assert listed(api_as(alice)) == listed(api_as(bob)) == []
    assert api_as(people[who]).delete(one(connection)).status_code == 404
    # Either may ask again afterwards.
    assert ask(api_as(bob), alice).status_code == 201


def test_taking_a_request_back_also_takes_back_its_notification(api_as):
    alice, bob = UserFactory(), UserFactory()
    connection_id = ask(api_as(alice), bob).json()["id"]
    assert Notification.objects.filter(recipient=bob).count() == 1

    response = api_as(alice).delete(f"{CONNECTIONS}{connection_id}/")

    assert response.status_code == 204
    assert not Connection.objects.exists()
    assert not Notification.objects.exists()
    assert listed(api_as(bob), "INCOMING") == []


def test_a_request_made_to_you_is_answered_not_deleted(api_as):
    alice, bob = UserFactory(), UserFactory()
    connection = make_connection(alice, bob, "REQUESTED")

    response = api_as(bob).delete(one(connection))

    assert (response.status_code, response.json()["code"]) == (409, "answer_instead")
    assert Connection.objects.filter(status="REQUESTED").exists()


def test_taking_back_a_declined_request_lets_you_ask_again(api_as):
    alice, bob = UserFactory(), UserFactory()
    connection = make_connection(alice, bob, "DECLINED")

    assert api_as(alice).delete(one(connection)).status_code == 204
    assert ask(api_as(alice), bob).status_code == 201


# --- Lists ------------------------------------------------------------------------------


def test_lists_are_only_ever_about_the_caller(api, api_as):
    alice, bob, carol, dave = (UserFactory() for _ in range(4))
    make_connection(alice, bob)
    make_connection(carol, alice)
    make_connection(bob, carol)
    make_connection(dave, alice, "REQUESTED")
    make_connection(alice, UserFactory(is_active=False))

    assert sorted(listed(api_as(alice))) == sorted(
        [(str(bob.pk), "CONNECTED"), (str(carol.pk), "CONNECTED")]
    )
    assert listed(api_as(dave)) == []
    assert listed(api_as(dave), "OUTGOING") == [(str(alice.pk), "OUTGOING")]
    # No parameter widens the list to somebody else's connections.
    widened = api_as(dave).get(CONNECTIONS, {"user_id": str(alice.pk), "user": str(alice.pk)})
    assert widened.json()["results"] == []
    assert api_as(alice).get(CONNECTIONS, {"state": "EVERYONE"}).status_code == 400
    assert api.get(CONNECTIONS).status_code == 401
    assert api.get(SUMMARY).status_code == 401


def test_the_list_is_paginated_and_uses_a_fixed_number_of_queries(
    api_as, django_assert_max_num_queries
):
    alice = UserFactory()
    for _ in range(25):
        make_connection(alice, UserFactory())
    client = api_as(alice)

    with django_assert_max_num_queries(3):
        page = client.get(CONNECTIONS).json()

    assert len(page["results"]) == 20
    assert page["next"] is not None
    assert len(client.get(page["next"]).json()["results"]) == 5


# --- Effects elsewhere ------------------------------------------------------------------


def test_a_block_removes_the_connection_and_any_request(api_as):
    alice, bob, carol = UserFactory(), UserFactory(), UserFactory()
    make_connection(alice, bob)
    ask(api_as(carol), alice)

    assert api_as(alice).put(f"/api/v1/users/{bob.pk}/block/").status_code == 204
    assert api_as(alice).put(f"/api/v1/users/{carol.pk}/block/").status_code == 204

    assert not Connection.objects.exists()
    assert not Notification.objects.filter(type="CONNECTION_REQUESTED").exists()
    # Lifting the block does not bring the connection back.
    api_as(alice).delete(f"/api/v1/users/{bob.pk}/block/")
    assert listed(api_as(alice)) == listed(api_as(bob)) == []


@pytest.mark.parametrize(
    ("visibility", "relation", "status"),
    [
        ("CONNECTIONS", "connected", 200),
        ("CONNECTIONS", "asked", 404),
        ("CONNECTIONS", "was_asked", 404),
        ("CONNECTIONS", "stranger", 404),
        ("COMMUNITY", "connected", 200),
        ("COMMUNITY", "stranger", 404),
        ("PRIVATE", "connected", 404),
    ],
)
def test_a_connections_only_profile_opens_for_connections_alone(
    api_as, visibility, relation, status
):
    owner, viewer = UserFactory(), UserFactory()
    UserProfile.objects.filter(pk=owner.pk).update(visibility=visibility)
    if relation == "connected":
        make_connection(viewer, owner)
    elif relation == "asked":
        make_connection(viewer, owner, "REQUESTED")
    elif relation == "was_asked":
        make_connection(owner, viewer, "REQUESTED")

    assert profile(api_as(viewer), owner).status_code == status


def test_a_profile_says_what_stands_between_its_owner_and_the_viewer(api_as):
    alice, bob, carol, dave = (UserFactory() for _ in range(4))
    connected = make_connection(alice, bob)
    outgoing = make_connection(alice, carol, "REQUESTED")
    incoming = make_connection(dave, alice, "REQUESTED")
    client = api_as(alice)

    assert profile(client, alice).json()["connection"] is None
    assert profile(client, UserFactory()).json()["connection"] is None
    assert profile(client, bob).json()["connection"] == {
        "id": str(connected.pk),
        "state": "CONNECTED",
    }
    assert profile(client, carol).json()["connection"] == {
        "id": str(outgoing.pk),
        "state": "OUTGOING",
    }
    assert profile(client, dave).json()["connection"] == {
        "id": str(incoming.pk),
        "state": "INCOMING",
    }
