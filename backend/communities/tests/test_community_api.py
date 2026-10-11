import uuid

import pytest

from audit.models import AuditLog
from communities.models import Community, CommunityMember, CommunityRule
from communities.tests.factories import (
    CommunityFactory,
    CommunityMemberFactory,
    community_with_roles,
)
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/communities/"


def detail(community) -> str:
    return f"{URL}{community.pk}/"


def client_for(api_as, api, members, who):
    if who == "anonymous":
        return api
    if who == "outsider":
        return api_as(UserFactory())
    return api_as(members[who].user)


# --- Create -----------------------------------------------------------------------------


def test_creating_a_community_makes_the_caller_its_owner(api_as):
    user = UserFactory()

    response = api_as(user).post(
        URL, {"name": " Kochi   Developers ", "category": "Technology", "join_policy": "APPROVAL"}
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["slug"]) == ("Kochi Developers", "kochi-developers")
    assert (body["join_policy"], body["visibility"]) == ("APPROVAL", "PUBLIC")
    assert body["posting_policy"] == "MEMBERS_WITH_APPROVAL"
    assert (body["member_count"], body["rules"]) == (1, [])
    viewer = body["viewer"]
    assert (viewer["role"], viewer["status"], viewer["join_action"]) == ("OWNER", "ACTIVE", None)
    assert viewer["can_manage"] and viewer["can_review_requests"]
    membership = CommunityMember.objects.get(community_id=body["id"])
    assert (membership.user, membership.role, membership.status) == (user, "OWNER", "ACTIVE")
    log = AuditLog.objects.get(action="community.created")
    assert (log.actor, str(log.community_id)) == (user, body["id"])


def test_clients_cannot_set_server_controlled_fields(api_as):
    response = api_as(UserFactory()).post(
        URL, {"name": "Kochi Developers", "is_verified": True, "slug": "official", "status": "X"}
    )

    community = Community.objects.get(pk=response.json()["id"])
    assert (community.is_verified, community.slug, community.status) == (
        False,
        "kochi-developers",
        "ACTIVE",
    )


def test_creating_requires_a_verified_account(api, api_as):
    anonymous = api.post(URL, {"name": "Kochi Developers"})
    unverified = api_as(UserFactory(unverified=True)).post(URL, {"name": "Kochi Developers"})

    assert anonymous.status_code == 401
    assert (unverified.status_code, unverified.json()["code"]) == (403, "email_not_verified")
    assert not Community.objects.exists()


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "name"),
        ({"name": "???"}, "name"),
        ({"name": "Devs", "join_policy": "WHENEVER"}, "join_policy"),
        ({"name": "Devs", "visibility": "SECRET"}, "visibility"),
        ({"name": "Devs", "posting_policy": "ANYONE"}, "posting_policy"),
    ],
)
def test_create_validates_input(api_as, body, field):
    response = api_as(UserFactory()).post(URL, body)

    assert response.status_code == 400
    assert list(response.json()["errors"]) == [field]


# --- Browse and view --------------------------------------------------------------------


def test_browsing_shows_public_communities_and_filters(api):
    CommunityFactory(name="Kochi Developers", category="Technology")
    CommunityFactory(name="React India", category="Technology")
    CommunityFactory(name="Startup Founders", category="Business")
    CommunityFactory(name="Secret Circle", visibility="PRIVATE")
    CommunityFactory(name="Suspended Group", status="SUSPENDED")

    def names(**params):
        return {c["name"] for c in api.get(URL, params).json()["results"]}

    assert names() == {"Kochi Developers", "React India", "Startup Founders"}
    assert names(q="kochi") == {"Kochi Developers"}
    assert names(q="raect india") == {"React India"}
    assert names(category="technology") == {"Kochi Developers", "React India"}


def test_list_counts_only_active_members_in_a_fixed_number_of_queries(
    api_as, django_assert_max_num_queries
):
    for _ in range(5):
        community, _ = community_with_roles("ADMIN")
        CommunityMemberFactory(community=community, status="PENDING")
        CommunityMemberFactory(community=community, status="BANNED")
    client = api_as(UserFactory())

    with django_assert_max_num_queries(3):
        results = client.get(URL).json()["results"]

    assert [c["member_count"] for c in results] == [2] * 5


@pytest.mark.parametrize(
    ("status", "sees"),
    [
        ("ACTIVE", True),
        ("INVITED", True),
        ("PENDING", False),
        ("LEFT", False),
        ("REMOVED", False),
        ("BANNED", False),
        (None, False),
    ],
)
def test_a_private_community_is_visible_only_to_members_and_invitees(api_as, status, sees):
    community = CommunityFactory(visibility="PRIVATE")
    user = UserFactory()
    if status:
        CommunityMemberFactory(community=community, user=user, status=status)
    client = api_as(user)

    listed = str(community.pk) in {c["id"] for c in client.get(URL).json()["results"]}

    assert client.get(detail(community)).status_code == (200 if sees else 404)
    assert listed is sees


def test_a_private_community_looks_nonexistent_to_visitors_but_not_to_staff(api, api_as):
    community = CommunityFactory(visibility="PRIVATE")

    hidden = api.get(detail(community))
    missing = api.get(f"{URL}{uuid.uuid7()}/")
    hidden_body, missing_body = hidden.json(), missing.json()
    hidden_body.pop("request_id")
    missing_body.pop("request_id")

    assert hidden.status_code == missing.status_code == 404
    assert hidden_body == missing_body
    assert api_as(UserFactory(platform_role="MODERATOR")).get(detail(community)).status_code == 200


@pytest.mark.parametrize(
    ("join_policy", "status", "action"),
    [
        ("OPEN", None, "join"),
        ("APPROVAL", None, "request"),
        ("INVITE_ONLY", None, None),
        ("INVITE_ONLY", "INVITED", "accept"),
        ("OPEN", "ACTIVE", None),
        ("APPROVAL", "PENDING", None),
        ("OPEN", "BANNED", None),
        ("OPEN", "LEFT", "join"),
        ("APPROVAL", "REMOVED", "request"),
    ],
)
def test_viewer_block_says_what_joining_would_do(api_as, join_policy, status, action):
    community = CommunityFactory(join_policy=join_policy)
    user = UserFactory()
    if status:
        CommunityMemberFactory(community=community, user=user, status=status)

    viewer = api_as(user).get(detail(community)).json()["viewer"]

    assert viewer["join_action"] == action
    # Having been removed, rejected or having left is not shown back to the person.
    shown = status if status in ("ACTIVE", "INVITED", "PENDING", "BANNED") else None
    assert viewer["status"] == shown
    assert viewer["role"] == ("MEMBER" if status == "ACTIVE" else None)
    assert viewer["can_manage"] is False


def test_mine_lists_memberships_invitations_and_requests(api, api_as):
    user = UserFactory()
    for status in ("ACTIVE", "INVITED", "PENDING", "LEFT", "BANNED"):
        CommunityMemberFactory(user=user, status=status)
    CommunityMemberFactory()  # someone else's

    mine = api_as(user).get(f"{URL}mine/").json()

    assert sorted(m["status"] for m in mine) == ["ACTIVE", "INVITED", "PENDING"]
    assert api.get(f"{URL}mine/").status_code == 401


# --- Edit and rules ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "status"),
    [
        ("OWNER", 200),
        ("ADMIN", 200),
        ("MODERATOR", 403),
        ("MEMBER", 403),
        ("outsider", 403),
        ("anonymous", 401),
    ],
)
def test_only_owners_and_admins_can_edit_and_set_rules(api, api_as, who, status):
    community, members = community_with_roles("ADMIN", "MODERATOR", "MEMBER")
    client = client_for(api_as, api, members, who)

    edited = client.patch(detail(community), {"join_policy": "INVITE_ONLY"})
    ruled = client.put(f"{detail(community)}rules/", {"rules": [{"title": "Be kind"}]})

    assert (edited.status_code, ruled.status_code) == (status, status)
    community.refresh_from_db()
    assert community.join_policy == ("INVITE_ONLY" if status == 200 else "OPEN")
    assert CommunityRule.objects.count() == (1 if status == 200 else 0)


def test_rules_are_replaced_in_order(api_as):
    community, members = community_with_roles()
    client = api_as(members["OWNER"].user)
    rules_url = f"{detail(community)}rules/"

    client.put(rules_url, {"rules": [{"title": "One"}, {"title": "Two", "body": "Details."}]})
    response = client.put(
        rules_url, {"rules": [{"title": "Two", "body": "Details."}, {"title": "Three"}]}
    )

    assert response.json()["rules"] == [
        {"title": "Two", "body": "Details."},
        {"title": "Three", "body": ""},
    ]
    stored = list(CommunityRule.objects.values_list("position", "title"))
    assert stored == [(1, "Two"), (2, "Three")]
    assert AuditLog.objects.filter(action="community.rules_updated").count() == 2
    assert client.put(rules_url, {"rules": []}).json()["rules"] == []


def test_rules_are_validated(api_as):
    community, members = community_with_roles()
    client = api_as(members["OWNER"].user)
    rules_url = f"{detail(community)}rules/"

    too_many = client.put(rules_url, {"rules": [{"title": f"Rule {n}"} for n in range(21)]})
    untitled = client.put(rules_url, {"rules": [{"body": "No title"}]})

    assert too_many.status_code == untitled.status_code == 400
    assert not CommunityRule.objects.exists()


def test_a_suspended_community_cannot_be_changed(api_as):
    community, members = community_with_roles()
    Community.objects.filter(pk=community.pk).update(status="SUSPENDED")
    client = api_as(members["OWNER"].user)

    assert client.get(detail(community)).status_code == 200  # members still see it
    edited = client.patch(detail(community), {"category": "Other"})
    assert (edited.status_code, edited.json()["code"]) == (422, "community_suspended")
