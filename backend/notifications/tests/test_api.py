import uuid

import pytest

from communities.tests.factories import CommunityFactory
from notifications import services
from notifications.models import Notification, NotificationPreference, NotificationType
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/notifications/"
PREFERENCES = "/api/v1/users/me/notification-preferences/"


def tell(recipient, actor=None, name="Kochi Developers"):
    community = CommunityFactory(name=name)
    return services.notify(
        recipient=recipient,
        type=NotificationType.COMMUNITY_JOIN_APPROVED,
        target=community,
        actor=actor,
        payload={"community_id": str(community.pk), "community_name": name},
    )


def test_a_notification_is_listed_already_worded(api_as):
    user, actor = UserFactory(), UserFactory(display_name="Grace Hopper")
    notification = tell(user, actor=actor)

    (item,) = api_as(user).get(URL).json()["results"]

    assert item == {
        "id": str(notification.pk),
        "type": "COMMUNITY_JOIN_APPROVED",
        "title": "You are now a member of Kochi Developers",
        "body": "Your request to join was approved.",
        "url": f"/communities/{notification.target_id}",
        "actor": {
            "id": str(actor.pk),
            "display_name": "Grace Hopper",
            "headline": "",
            "avatar_url": None,
        },
        "is_read": False,
        "created_at": item["created_at"],
    }
    # Nothing internal leaks out with it.
    assert not {"payload", "dedupe_key", "recipient", "target_id"} & set(item)


def test_the_list_is_newest_first_and_only_ones_own(api, api_as):
    user, other = UserFactory(), UserFactory()
    for name in ("First", "Second", "Third"):
        tell(user, name=name)
    tell(other, name="Someone else's")
    client = api_as(user)

    titles = [item["title"] for item in client.get(URL).json()["results"]]

    assert titles == [f"You are now a member of {name}" for name in ("Third", "Second", "First")]
    assert client.get(f"{URL}unread-count/").json() == {"count": 3}
    assert api.get(URL).status_code == 401
    assert api.get(f"{URL}unread-count/").status_code == 401


def test_marking_read(api_as):
    user, other = UserFactory(), UserFactory()
    first, second = tell(user, name="First"), tell(user, name="Second")
    theirs = tell(other)
    client = api_as(user)

    assert client.post(f"{URL}{first.pk}/read/").status_code == 204
    assert client.post(f"{URL}{first.pk}/read/").status_code == 204  # repeating is harmless
    # Someone else's notification and a missing one look the same.
    assert client.post(f"{URL}{theirs.pk}/read/").status_code == 404
    assert client.post(f"{URL}{uuid.uuid7()}/read/").status_code == 404

    assert client.get(f"{URL}unread-count/").json() == {"count": 1}
    unread = client.get(URL, {"unread": "true"}).json()["results"]
    assert [item["id"] for item in unread] == [str(second.pk)]
    everything = client.get(URL).json()["results"]
    assert {item["id"]: item["is_read"] for item in everything} == {
        str(first.pk): True,
        str(second.pk): False,
    }
    theirs.refresh_from_db()
    assert theirs.read_at is None


def test_marking_all_read_touches_only_ones_own(api_as):
    user, other = UserFactory(), UserFactory()
    for _ in range(3):
        tell(user)
    tell(other)
    client = api_as(user)

    assert client.post(f"{URL}read-all/").status_code == 204
    assert client.post(f"{URL}read-all/").status_code == 204

    assert client.get(f"{URL}unread-count/").json() == {"count": 0}
    assert api_as(other).get(f"{URL}unread-count/").json() == {"count": 1}


def test_the_list_takes_a_fixed_number_of_queries(api_as, django_assert_max_num_queries):
    user = UserFactory()
    for _ in range(15):
        tell(user, actor=UserFactory())
    client = api_as(user)

    with django_assert_max_num_queries(3):
        assert len(client.get(URL).json()["results"]) == 15


# --- Preferences ------------------------------------------------------------------------


def test_preferences_start_at_the_defaults_and_explain_each_category(api, api_as):
    response = api_as(UserFactory()).get(PREFERENCES)

    preferences = {p["category"]: p for p in response.json()["preferences"]}
    assert set(preferences) == {
        "INVITATIONS",
        "MEMBERSHIP",
        "REVIEW",
        "POSTINGS",
        "APPLICATIONS",
        "CONNECTIONS",
        "REFERRALS",
        "EVENTS",
        "MODERATION",
    }
    assert (preferences["REVIEW"]["in_app"], preferences["REVIEW"]["email"]) == (True, False)
    assert (preferences["POSTINGS"]["in_app"], preferences["POSTINGS"]["email"]) == (True, True)
    assert preferences["REVIEW"]["title"] == "Things waiting for my review"
    assert preferences["REVIEW"]["description"]
    assert api.get(PREFERENCES).status_code == 401


def test_setting_preferences_changes_only_what_was_sent(api_as):
    user, other = UserFactory(), UserFactory()
    client = api_as(user)

    response = client.put(
        PREFERENCES,
        {"preferences": [{"category": "POSTINGS", "in_app": True, "email": False}]},
    )
    client.put(
        PREFERENCES,
        {"preferences": [{"category": "POSTINGS", "in_app": False, "email": False}]},
    )

    assert response.status_code == 200
    stored = {
        p["category"]: (p["in_app"], p["email"])
        for p in client.get(PREFERENCES).json()["preferences"]
    }
    assert stored["POSTINGS"] == (False, False)
    assert stored["MEMBERSHIP"] == (True, True)  # untouched
    assert NotificationPreference.objects.filter(user=user).count() == 1  # updated in place
    assert not NotificationPreference.objects.filter(user=other).exists()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"preferences": [{"category": "EVERYTHING", "in_app": True, "email": True}]},
        {"preferences": [{"category": "POSTINGS", "in_app": True}]},
        {
            "preferences": [
                {"category": "POSTINGS", "in_app": True, "email": True},
                {"category": "POSTINGS", "in_app": False, "email": False},
            ]
        },
    ],
)
def test_preferences_are_validated(api_as, body):
    user = UserFactory()

    assert api_as(user).put(PREFERENCES, body).status_code == 400
    assert not NotificationPreference.objects.filter(user=user).exists()


def test_turning_a_category_off_stops_new_notifications_but_keeps_old_ones(api_as):
    user = UserFactory()
    client = api_as(user)
    tell(user, name="Before")

    client.put(
        PREFERENCES, {"preferences": [{"category": "MEMBERSHIP", "in_app": False, "email": False}]}
    )
    tell(user, name="After")

    assert [n["title"] for n in client.get(URL).json()["results"]] == [
        "You are now a member of Before"
    ]
    assert Notification.objects.filter(recipient=user).count() == 1
