"""The WebSocket, driven end to end through Channels' test communicator.

Each test is one coroutine, run on a single event loop. The consumer reaches the database
from a worker thread, so these tests need real (committed) transactions.
"""

import asyncio
from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator, OriginValidator
from channels.testing import WebsocketCommunicator
from django.core.cache import cache

from communities.tests.factories import CommunityFactory
from config.asgi import application
from config.routing import websocket_urlpatterns
from conftest import SAME_ORIGIN
from notifications import services as notifications
from notifications.models import NotificationType
from realtime import events, tickets
from realtime.consumers import StreamConsumer
from users.models import User
from users.services import auth
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)

UNAUTHENTICATED, IDLE, TOO_LARGE = 4401, 4408, 1009


def run(scenario):
    return async_to_sync(scenario)()


def socket_for(ticket: str, app=None, **extra) -> WebsocketCommunicator:
    return WebsocketCommunicator(
        app or StreamConsumer.as_asgi(), f"/ws/stream/?ticket={ticket}", **extra
    )


async def open_socket(user) -> WebsocketCommunicator:
    """A connected socket for the user, with the greeting already read."""
    socket = socket_for(tickets.issue(user))
    connected, _ = await socket.connect()
    assert connected
    assert (await socket.receive_json_from())["type"] == "hello"
    return socket


async def close_code(socket: WebsocketCommunicator) -> int:
    message = await socket.receive_output(timeout=2)
    assert message["type"] == "websocket.close", message
    return int(message["code"])


in_thread = database_sync_to_async


# --- Connecting -------------------------------------------------------------------------


def test_a_ticket_opens_the_socket_and_the_server_says_hello():
    user = UserFactory()

    async def scenario():
        socket = socket_for(tickets.issue(user))
        connected, _ = await socket.connect()
        hello = await socket.receive_json_from()
        await socket.disconnect()
        return connected, hello

    connected, hello = run(scenario)

    assert connected
    assert set(hello) == {"event_id", "type", "occurred_at", "data"}
    assert hello["type"] == "hello"
    assert set(hello["data"]) == {"server_time", "session_expires_at", "heartbeat_seconds"}
    assert hello["data"]["heartbeat_seconds"] == 30


def test_a_ticket_works_only_once():
    user = UserFactory()
    ticket = tickets.issue(user)

    async def scenario():
        first = socket_for(ticket)
        await first.connect()
        await first.receive_json_from()
        second = socket_for(ticket)
        await second.connect()
        code = await close_code(second)
        await first.disconnect()
        return code

    assert run(scenario) == UNAUTHENTICATED


@pytest.mark.parametrize("ticket", ["", "not-a-ticket", "x" * 500, "../../etc/passwd"])
def test_a_bad_ticket_is_refused_with_the_unauthenticated_code(ticket):
    async def scenario():
        socket = socket_for(ticket)
        await socket.connect()
        return await close_code(socket)

    assert run(scenario) == UNAUTHENTICATED


def test_an_expired_ticket_and_a_deactivated_user_are_refused():
    expired = tickets.issue(UserFactory())
    cache.clear()  # what the 30-second timeout does
    deactivated = UserFactory()
    for_deactivated = tickets.issue(deactivated)
    User.objects.filter(pk=deactivated.pk).update(is_active=False)

    async def scenario():
        codes = []
        for ticket in (expired, for_deactivated):
            socket = socket_for(ticket)
            await socket.connect()
            codes.append(await close_code(socket))
        return codes

    assert run(scenario) == [UNAUTHENTICATED, UNAUTHENTICATED]


def test_a_ticket_is_bound_to_one_user_and_is_spent_by_redeeming_it():
    user, other = UserFactory(), UserFactory()

    ticket = tickets.issue(user)

    assert tickets.redeem(ticket) == user.pk
    assert tickets.redeem(ticket) is None
    assert tickets.redeem(tickets.issue(other)) == other.pk


@pytest.mark.parametrize(
    ("origin", "accepted"),
    [(b"http://testserver", True), (b"https://evil.example", False), (None, False)],
)
def test_only_our_own_origin_may_open_the_socket(origin, accepted, settings):
    settings.ALLOWED_HOSTS = ["testserver"]
    # Built here, the way config.asgi builds it: the validator reads the allowed hosts once.
    guarded = AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns))
    user = UserFactory()
    ticket = tickets.issue(user)
    headers = [(b"origin", origin)] if origin else []

    async def scenario():
        socket = socket_for(ticket, app=guarded, headers=headers)
        connected, _ = await socket.connect()
        if connected:
            await socket.disconnect()
        return connected

    assert run(scenario) is accepted
    # A refused origin never reaches the consumer, so the ticket was not even spent.
    assert (tickets.redeem(ticket) is None) is accepted


def test_the_deployed_application_puts_the_origin_check_in_front_of_the_socket():
    assert isinstance(application.application_mapping["websocket"], OriginValidator)


# --- Receiving --------------------------------------------------------------------------


def test_an_event_reaches_every_socket_of_its_user_and_nobody_else():
    alice, bob = UserFactory(), UserFactory()

    async def scenario():
        phone, laptop, bobs = [await open_socket(u) for u in (alice, alice, bob)]
        await in_thread(events.publish)(alice.pk, "notification.created", {"id": "n-1"})
        received = [await phone.receive_json_from(), await laptop.receive_json_from()]
        bob_got_nothing = await bobs.receive_nothing(timeout=0.2)
        for socket in (phone, laptop, bobs):
            await socket.disconnect()
        return received, bob_got_nothing

    received, bob_got_nothing = run(scenario)

    assert bob_got_nothing
    for event in received:
        assert (event["type"], event["data"]) == ("notification.created", {"id": "n-1"})
        assert event["event_id"] and event["occurred_at"]
    # Both tabs get the same event ID, which is what lets a client ignore a repeat.
    assert received[0]["event_id"] == received[1]["event_id"]


def test_a_client_cannot_subscribe_to_anything_or_send_events():
    alice, bob = UserFactory(), UserFactory()

    async def scenario():
        socket = await open_socket(alice)
        for attempt in (
            {"type": "subscribe", "group": f"user.{bob.pk}"},
            {"type": "stream.event", "event": {"type": "forged"}},
            {"type": "session.revoked"},
        ):
            await socket.send_json_to(attempt)
        await in_thread(events.publish)(bob.pk, "notification.created", {"secret": True})
        nothing = await socket.receive_nothing(timeout=0.3)
        await socket.disconnect()
        return nothing

    assert run(scenario)


def test_heartbeat_and_junk_input():
    user = UserFactory()

    async def scenario():
        socket = await open_socket(user)
        await socket.send_json_to({"type": "ping"})
        pong = await socket.receive_json_from()
        for junk in ("not json", "[]", "null", '{"type": 5}'):
            await socket.send_to(text_data=junk)
        quiet = await socket.receive_nothing(timeout=0.2)
        await socket.send_to(text_data="x" * 1000)
        code = await close_code(socket)
        return pong, quiet, code

    pong, quiet, code = run(scenario)

    assert pong == {"type": "pong"}
    assert quiet  # junk is ignored, not answered and not fatal
    assert code == TOO_LARGE


def test_a_silent_socket_is_dropped_and_a_live_one_is_kept(settings):
    settings.WS_IDLE_TIMEOUT = timedelta(seconds=0.4)
    user = UserFactory()

    async def scenario():
        silent, lively = await open_socket(user), await open_socket(user)
        for _ in range(8):
            await asyncio.sleep(0.1)
            await lively.send_json_to({"type": "ping"})
            assert await lively.receive_json_from() == {"type": "pong"}
        code = await close_code(silent)
        await lively.disconnect()
        return code

    assert run(scenario) == IDLE


def test_a_socket_is_closed_at_the_session_cap_even_if_active(settings):
    settings.WS_SESSION_MAX_AGE = timedelta(seconds=0.3)
    user = UserFactory()

    async def scenario():
        socket = await open_socket(user)
        await socket.send_json_to({"type": "ping"})
        await socket.receive_json_from()
        return await close_code(socket)

    # The same code as a bad ticket: the client's response is the same, get a new one.
    assert run(scenario) == UNAUTHENTICATED


# --- Wired to the rest of the system ----------------------------------------------------


def tell(recipient, actor):
    community = CommunityFactory(name="Kochi Developers")
    return notifications.notify(
        recipient=recipient,
        type=NotificationType.COMMUNITY_JOIN_APPROVED,
        target=community,
        actor=actor,
        payload={"community_id": str(community.pk), "community_name": community.name},
    )


def test_a_new_notification_is_pushed_in_the_same_shape_as_the_api_returns(api_as):
    user, actor = UserFactory(), UserFactory()

    async def scenario():
        socket = await open_socket(user)
        notification = await in_thread(tell)(user, actor)
        event = await socket.receive_json_from()
        await socket.disconnect()
        return notification, event

    notification, event = run(scenario)

    assert event["type"] == "notification.created"
    assert event["data"]["id"] == str(notification.pk)
    (listed,) = api_as(user).get("/api/v1/notifications/").json()["results"]
    assert event["data"] == listed


def test_a_notification_hidden_from_the_app_is_not_pushed():
    user = UserFactory()
    notifications.set_preferences(
        user=user, choices={notifications.Category.MEMBERSHIP: (False, True)}
    )

    async def scenario():
        socket = await open_socket(user)
        await in_thread(tell)(user, None)
        nothing = await socket.receive_nothing(timeout=0.3)
        await socket.disconnect()
        return nothing

    assert run(scenario)


def test_marking_read_is_announced_to_the_users_other_tabs():
    user = UserFactory()
    first, second = tell(user, None), tell(user, None)

    async def scenario():
        socket = await open_socket(user)
        await in_thread(notifications.mark_read)(user=user, notification_id=first.pk)
        one = await socket.receive_json_from()
        # Nothing changed, so nothing is announced.
        await in_thread(notifications.mark_read)(user=user, notification_id=first.pk)
        quiet = await socket.receive_nothing(timeout=0.2)
        await in_thread(notifications.mark_all_read)(user=user)
        everything = await socket.receive_json_from()
        await socket.disconnect()
        return one, quiet, everything

    one, quiet, everything = run(scenario)

    assert (one["type"], one["data"]) == ("notification.read", {"ids": [str(first.pk)]})
    assert quiet
    assert (everything["type"], everything["data"]) == ("notification.read", {"all": True})
    assert second.pk  # was unread until mark_all_read


def test_signing_out_and_changing_the_password_close_the_users_sockets(api):
    user, bystander = UserFactory(), UserFactory()
    login = api.post(
        "/api/v1/auth/login/", {"email": user.email, "password": "correct-horse-battery"}
    )
    assert login.status_code == 200

    async def scenario():
        signed_out, other = await open_socket(user), await open_socket(bystander)
        response = await in_thread(api.post)("/api/v1/auth/logout/", headers=SAME_ORIGIN)
        first = await close_code(signed_out)

        changed = await open_socket(user)
        await in_thread(auth.change_password)(
            user=user,
            current_password="correct-horse-battery",
            new_password="a-brand-new-passphrase",
        )
        second = await close_code(changed)
        untouched = await other.receive_nothing(timeout=0.2)
        await other.disconnect()
        return response.status_code, first, second, untouched

    assert run(scenario) == (204, UNAUTHENTICATED, UNAUTHENTICATED, True)


# --- The ticket endpoint ----------------------------------------------------------------


def test_only_a_signed_in_user_gets_a_ticket_and_it_opens_their_socket(api, api_as):
    user = UserFactory()

    response = api_as(user).post("/api/v1/auth/ws-ticket/")

    assert response.status_code == 200
    assert response.json()["expires_in"] == 30
    assert tickets.redeem(response.json()["ticket"]) == user.pk
    assert api.post("/api/v1/auth/ws-ticket/").status_code == 401


def test_tickets_are_rate_limited(api_as, monkeypatch):
    from common.throttles import ScopedThrottle

    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "ws_ticket", "2/min")
    client = api_as(UserFactory())

    codes = [client.post("/api/v1/auth/ws-ticket/").status_code for _ in range(3)]

    assert codes == [200, 200, 429]
