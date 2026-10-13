import threading
import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from common.throttles import ScopedThrottle
from connections.tests.factories import make_connection
from messaging import services
from messaging.models import Conversation, ConversationParticipant, Message
from realtime import events
from users.models import User, UserBlock
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/conversations/"


def friends():
    a, b = UserFactory(), UserFactory()
    make_connection(a, b)
    return a, b


def talking():
    """Two connected people with a conversation already open."""
    a, b = friends()
    conversation, _ = services.start(user=a, user_id=b.pk)
    return a, b, conversation


def say(user, conversation, body="Hello", **fields):
    message, _ = services.send(
        user=user, conversation_id=conversation.pk, body=body, client_id=uuid.uuid4()
    )
    if fields:
        Message.objects.filter(pk=message.pk).update(**fields)
    return message


def messages(conversation) -> str:
    return f"{URL}{conversation.pk}/messages/"


# --- Starting ---------------------------------------------------------------------------


def test_connections_can_start_a_conversation_and_there_is_one_per_pair(api_as):
    ada, bob = friends()

    created = api_as(ada).post(URL, {"user_id": str(bob.pk)})

    assert created.status_code == 201
    body = created.json()
    assert body["other"]["id"] == str(bob.pk)
    assert (body["unread_count"], body["last_message_preview"], body["other_read_at"]) == (
        0,
        "",
        None,
    )
    # Opening it again, from either side, finds the same one.
    again = api_as(ada).post(URL, {"user_id": str(bob.pk)})
    from_bob = api_as(bob).post(URL, {"user_id": str(ada.pk)})
    assert (again.status_code, from_bob.status_code) == (200, 200)
    assert again.json()["id"] == from_bob.json()["id"] == body["id"]
    assert from_bob.json()["other"]["id"] == str(ada.pk)
    assert Conversation.objects.count() == 1
    assert ConversationParticipant.objects.count() == 2


def test_who_cannot_start_a_conversation(api, api_as):
    ada, stranger, pending = UserFactory(), UserFactory(), UserFactory()
    make_connection(ada, pending, status="REQUESTED")
    client = api_as(ada)

    for other in (stranger, pending):
        response = client.post(URL, {"user_id": str(other.pk)})
        assert (response.status_code, response.json()["code"]) == (422, "not_connected")
    assert client.post(URL, {"user_id": str(ada.pk)}).status_code == 404  # oneself
    assert client.post(URL, {"user_id": str(uuid.uuid4())}).status_code == 404
    assert client.post(URL, {"user_id": "nope"}).status_code == 400
    assert api.post(URL, {"user_id": str(stranger.pk)}).status_code == 401
    unverified = UserFactory(unverified=True)
    make_connection(unverified, stranger)
    refused = api_as(unverified).post(URL, {"user_id": str(stranger.pk)})
    assert (refused.status_code, refused.json()["code"]) == (403, "email_not_verified")
    assert not Conversation.objects.exists()


def test_a_private_profile_does_not_stop_a_connection_from_writing(api_as):
    ada, bob = friends()
    bob.profile.visibility = "PRIVATE"
    bob.profile.save()

    assert api_as(ada).post(URL, {"user_id": str(bob.pk)}).status_code == 201


def test_a_conversation_outlives_the_connection_but_a_new_one_needs_it(api_as):
    ada, bob, conversation = talking()
    from connections.selectors import between

    between(ada.pk, bob.pk).delete()

    assert api_as(ada).post(URL, {"user_id": str(bob.pk)}).status_code == 200
    assert api_as(bob).post(messages(conversation), _body("Still here")).status_code == 201


def _body(text="Hello", client_id=None):
    return {"body": text, "client_id": str(client_id or uuid.uuid4())}


# --- Sending ----------------------------------------------------------------------------


def test_sending_a_message(api_as, django_capture_on_commit_callbacks, monkeypatch):
    published = []
    monkeypatch.setattr(events, "publish", lambda *args: published.append(args))
    ada, bob, conversation = talking()

    with django_capture_on_commit_callbacks(execute=True):
        response = api_as(ada).post(messages(conversation), _body("  Hello Bob!  "))

    assert response.status_code == 201
    body = response.json()
    assert (body["body"], body["sender_id"]) == ("Hello Bob!", str(ada.pk))
    assert body["conversation_id"] == str(conversation.pk)
    # Both people's open pages are nudged, with IDs only: the text travels over the API.
    hint = {"conversation_id": str(conversation.pk), "message_id": body["id"]}
    assert sorted(published) == sorted(
        [(str(bob.pk), "message.created", hint), (str(ada.pk), "message.created", hint)]
    )
    assert "Hello Bob!" not in str(published)

    # The inbox reflects it for each of them.
    (mine,) = api_as(ada).get(URL).json()["results"]
    (theirs,) = api_as(bob).get(URL).json()["results"]
    assert (mine["last_message_preview"], mine["unread_count"]) == ("Hello Bob!", 0)
    assert (theirs["last_message_preview"], theirs["unread_count"]) == ("Hello Bob!", 1)
    assert api_as(bob).get(f"{URL}unread-count/").json() == {"count": 1}
    assert api_as(ada).get(f"{URL}unread-count/").json() == {"count": 0}


def test_a_retry_with_the_same_client_id_does_not_send_twice(api_as):
    ada, _, conversation = talking()
    client, once = api_as(ada), uuid.uuid4()

    first = client.post(messages(conversation), _body("Hello", once))
    retry = client.post(messages(conversation), _body("Hello", once))
    changed = client.post(messages(conversation), _body("Something else", once))

    assert (first.status_code, retry.status_code, changed.status_code) == (201, 200, 200)
    assert first.json()["id"] == retry.json()["id"] == changed.json()["id"]
    assert changed.json()["body"] == "Hello"
    assert Message.objects.count() == 1


def test_the_same_client_id_from_the_other_person_is_a_different_message(api_as):
    ada, bob, conversation = talking()
    shared = uuid.uuid4()

    assert api_as(ada).post(messages(conversation), _body("From Ada", shared)).status_code == 201
    assert api_as(bob).post(messages(conversation), _body("From Bob", shared)).status_code == 201
    assert Message.objects.count() == 2


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"body": "", "client_id": str(uuid.uuid4())}, 400),
        ({"body": "   \n  ", "client_id": str(uuid.uuid4())}, 400),
        ({"body": "x" * 4001, "client_id": str(uuid.uuid4())}, 400),
        ({"body": "Hello"}, 400),
        ({"body": "Hello", "client_id": "not-a-uuid"}, 400),
        ({"client_id": str(uuid.uuid4())}, 400),
    ],
)
def test_send_validates_input(api_as, body, status):
    ada, _, conversation = talking()

    assert api_as(ada).post(messages(conversation), body).status_code == status
    assert not Message.objects.exists()


def test_a_message_is_kept_exactly_as_written(api_as):
    ada, bob, conversation = talking()
    text = "<script>alert('x')</script>\n  indented line\n😀 x" + "y" * 3000

    sent = api_as(ada).post(messages(conversation), _body(text)).json()

    assert sent["body"] == text
    (preview,) = api_as(bob).get(URL).json()["results"]
    assert preview["last_message_preview"] == text[:140]


def test_only_the_two_people_in_a_conversation_can_use_it(api, api_as):
    ada, bob, conversation = talking()
    say(ada, conversation)
    outsider, staff = api_as(UserFactory()), api_as(UserFactory(platform_role="ADMIN"))
    last = Message.objects.get()

    for client in (outsider, staff):
        assert client.get(f"{URL}{conversation.pk}/").status_code == 404
        assert client.get(messages(conversation)).status_code == 404
        assert client.post(messages(conversation), _body()).status_code == 404
        assert (
            client.post(
                f"{URL}{conversation.pk}/read/", {"up_to_message_id": str(last.pk)}
            ).status_code
            == 404
        )
        assert client.get(URL).json()["results"] == []
    assert api.get(URL).status_code == 401
    assert api.get(messages(conversation)).status_code == 401
    assert Message.objects.count() == 1


def test_messages_cannot_be_sent_to_someone_who_has_left(api_as):
    ada, bob, conversation = talking()
    User.objects.filter(pk=bob.pk).update(is_active=False)

    response = api_as(ada).post(messages(conversation), _body())

    assert (response.status_code, response.json()["code"]) == (422, "recipient_unavailable")


def test_sending_is_rate_limited(api_as, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "message_send", "2/min")
    ada, _, conversation = talking()
    client = api_as(ada)

    codes = [client.post(messages(conversation), _body()).status_code for _ in range(3)]

    assert codes == [201, 201, 429]


# --- Reading ----------------------------------------------------------------------------


def test_a_thread_pages_back_from_the_newest(api_as, django_assert_max_num_queries):
    ada, bob, conversation = talking()
    start = timezone.now() - timedelta(hours=1)
    for index in range(25):
        say(
            ada if index % 2 else bob,
            conversation,
            f"Message {index}",
            created_at=start + timedelta(seconds=index),
        )
    client = api_as(ada)

    with django_assert_max_num_queries(5):
        first = client.get(messages(conversation)).json()

    assert [m["body"] for m in first["results"]][:3] == ["Message 24", "Message 23", "Message 22"]
    assert len(first["results"]) == 20 and first["next"]
    older = client.get(first["next"]).json()
    assert [m["body"] for m in older["results"]] == [f"Message {i}" for i in range(4, -1, -1)]
    assert older["next"] is None
    assert set(first["results"][0]) == {
        "id",
        "conversation_id",
        "sender_id",
        "body",
        "client_id",
        "created_at",
    }


def test_reading_moves_the_position_forward_only(
    api_as, django_capture_on_commit_callbacks, monkeypatch
):
    published = []
    monkeypatch.setattr(events, "publish", lambda *args: published.append(args))
    ada, bob, conversation = talking()
    start = timezone.now() - timedelta(minutes=10)
    first, second, third = (
        say(ada, conversation, f"M{i}", created_at=start + timedelta(minutes=i)) for i in range(3)
    )
    bobs = api_as(bob)
    read = f"{URL}{conversation.pk}/read/"

    def unread():
        return bobs.get(f"{URL}{conversation.pk}/").json()["unread_count"]

    assert unread() == 3
    with django_capture_on_commit_callbacks(execute=True):
        assert bobs.post(read, {"up_to_message_id": str(second.pk)}).status_code == 204
    assert unread() == 1
    # Both are told: Bob's other tabs clear the badge, Ada sees how far he read.
    hint = {"conversation_id": str(conversation.pk)}
    assert sorted(published) == sorted(
        [(str(bob.pk), "conversation.read", hint), (str(ada.pk), "conversation.read", hint)]
    )
    seen = api_as(ada).get(f"{URL}{conversation.pk}/").json()["other_read_at"]
    assert seen is not None and seen[:19] == (start + timedelta(minutes=1)).isoformat()[:19]

    # An older message afterwards changes nothing, and announces nothing.
    published.clear()
    with django_capture_on_commit_callbacks(execute=True):
        assert bobs.post(read, {"up_to_message_id": str(first.pk)}).status_code == 204
    assert unread() == 1 and published == []

    assert bobs.post(read, {"up_to_message_id": str(third.pk)}).status_code == 204
    assert unread() == 0
    assert bobs.get(f"{URL}unread-count/").json() == {"count": 0}


def test_a_message_from_another_conversation_cannot_be_used_to_mark_read(api_as):
    ada, bob, conversation = talking()
    carol = UserFactory()
    make_connection(ada, carol)
    elsewhere, _ = services.start(user=ada, user_id=carol.pk)
    foreign = say(carol, elsewhere)
    say(bob, conversation)
    read = f"{URL}{conversation.pk}/read/"

    assert api_as(ada).post(read, {"up_to_message_id": str(foreign.pk)}).status_code == 404
    assert api_as(ada).post(read, {"up_to_message_id": str(uuid.uuid4())}).status_code == 404
    assert api_as(ada).post(read, {}).status_code == 400
    assert api_as(ada).get(f"{URL}{conversation.pk}/").json()["unread_count"] == 1


def test_your_own_messages_are_never_unread_to_you(api_as):
    ada, bob, conversation = talking()
    say(ada, conversation)
    say(ada, conversation)

    assert api_as(ada).get(f"{URL}unread-count/").json() == {"count": 0}
    assert api_as(bob).get(f"{URL}unread-count/").json() == {"count": 1}  # one conversation


def test_the_inbox_is_ordered_by_latest_activity_in_a_fixed_number_of_queries(
    api_as, django_assert_max_num_queries
):
    me = UserFactory()
    conversations = []
    for index in range(6):
        other = UserFactory()
        make_connection(me, other)
        conversation, _ = services.start(user=me, user_id=other.pk)
        say(other, conversation, f"From {index}")
        Conversation.objects.filter(pk=conversation.pk).update(
            last_message_at=timezone.now() - timedelta(hours=6 - index)
        )
        conversations.append(conversation)
    say(UserFactory._meta.model.objects.get(pk=conversations[0].other_id(me.pk)), conversations[0])

    with django_assert_max_num_queries(4):
        rows = api_as(me).get(URL).json()["results"]

    assert [row["id"] for row in rows][0] == str(conversations[0].pk)  # just written in
    assert [row["id"] for row in rows][1:] == [str(c.pk) for c in reversed(conversations[1:])]
    assert rows[0]["unread_count"] == 2 and rows[1]["unread_count"] == 1
    assert api_as(me).get(f"{URL}unread-count/").json() == {"count": 6}


# --- Blocking ---------------------------------------------------------------------------


def test_a_block_makes_the_conversation_vanish_for_both_and_unblocking_restores_it(api_as):
    ada, bob, conversation = talking()
    say(ada, conversation)
    block = UserBlock.objects.create(blocker=bob, blocked=ada)

    for user in (ada, bob):
        client = api_as(user)
        assert client.get(URL).json()["results"] == []
        assert client.get(f"{URL}{conversation.pk}/").status_code == 404
        assert client.get(messages(conversation)).status_code == 404
        assert client.post(messages(conversation), _body()).status_code == 404
        assert client.get(f"{URL}unread-count/").json() == {"count": 0}
    # Neither can reopen it, and the answer does not say who blocked whom.
    assert api_as(ada).post(URL, {"user_id": str(bob.pk)}).status_code == 404
    assert api_as(bob).post(URL, {"user_id": str(ada.pk)}).status_code == 404
    assert Message.objects.count() == 1

    block.delete()
    assert len(api_as(ada).get(messages(conversation)).json()["results"]) == 1


# --- The database's own rules -----------------------------------------------------------


def test_the_database_refuses_what_the_service_never_does():
    ada, bob, conversation = talking()
    low, high = sorted([ada.pk, bob.pk])

    with pytest.raises(IntegrityError), transaction.atomic():
        Conversation.objects.create(user_low_id=low, user_high_id=high)  # a second thread
    with pytest.raises(IntegrityError), transaction.atomic():
        Conversation.objects.create(user_low_id=high, user_high_id=low)  # the pair reversed
    with pytest.raises(IntegrityError), transaction.atomic():
        Conversation.objects.create(user_low=ada, user_high=ada)  # with oneself
    for body in ("", "   ", "x" * 4001):
        with pytest.raises(IntegrityError), transaction.atomic():
            Message.objects.create(
                conversation=conversation, sender=ada, body=body, client_id=uuid.uuid4()
            )
    once = uuid.uuid4()
    Message.objects.create(conversation=conversation, sender=ada, body="Hi", client_id=once)
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(conversation=conversation, sender=ada, body="Hi", client_id=once)


# --- Races ------------------------------------------------------------------------------


def run_together(*calls):
    barrier = threading.Barrier(len(calls))
    outcomes = [None] * len(calls)

    def run(index, call):
        barrier.wait()
        try:
            outcomes[index] = call()
        except Exception as exc:
            outcomes[index] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=item) for item in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    return outcomes


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_both_people_starting_at_once_get_one_conversation():
    ada, bob = friends()

    outcomes = run_together(
        lambda: services.start(user=ada, user_id=bob.pk),
        lambda: services.start(user=bob, user_id=ada.pk),
    )

    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    assert outcomes[0][0].pk == outcomes[1][0].pk
    assert sum(created for _, created in outcomes) == 1
    assert Conversation.objects.count() == 1
    assert ConversationParticipant.objects.count() == 2


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_a_double_send_and_messages_from_both_sides_at_once():
    ada, bob, conversation = talking()
    once = uuid.uuid4()

    def send(user, text, client_id):
        return lambda: services.send(
            user=user, conversation_id=conversation.pk, body=text, client_id=client_id
        )

    outcomes = run_together(
        send(ada, "Sent twice", once),
        send(ada, "Sent twice", once),
        send(ada, "From Ada", uuid.uuid4()),
        send(bob, "From Bob", uuid.uuid4()),
    )

    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    assert sorted(Message.objects.values_list("body", flat=True)) == [
        "From Ada",
        "From Bob",
        "Sent twice",
    ]
    # The preview is the message that really is the newest.
    conversation.refresh_from_db()
    newest = Message.objects.order_by("-created_at", "-id").first()
    assert conversation.last_message_preview == newest.body
    assert conversation.last_message_at == newest.created_at
