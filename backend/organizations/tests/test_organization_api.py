import uuid

import pytest

from audit.models import AuditLog
from common.throttles import ScopedThrottle
from organizations.models import Organization, OrganizationMember
from organizations.tests.factories import (
    MemberFactory,
    OrganizationFactory,
    organization_with_roles,
)
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/organizations/"


def detail(organization) -> str:
    return f"{URL}{organization.pk}/"


def client_for(api_as, api, members, who):
    """A client for a role in the organization, an unrelated user, or nobody."""
    if who == "anonymous":
        return api
    if who == "outsider":
        return api_as(UserFactory())
    return api_as(members[who].user)


# --- Create -----------------------------------------------------------------------------


def test_creating_an_organization_makes_the_caller_its_owner(api_as):
    user = UserFactory()

    response = api_as(user).post(
        URL, {"name": "  Example   Labs ", "country_code": "in", "website": "https://example.com"}
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["slug"]) == ("Example Labs", "example-labs")
    assert body["country_code"] == "IN"
    assert body["verification_status"] == "UNVERIFIED"
    assert body["member_count"] == 1
    assert body["viewer"]["role"] == "OWNER"
    assert body["viewer"]["can_manage"] is True
    assert set(body["viewer"]["assignable_roles"]) == {"OWNER", "ADMIN", "RECRUITER", "MEMBER"}
    membership = OrganizationMember.objects.get(organization_id=body["id"])
    assert (membership.user, membership.role, membership.status) == (user, "OWNER", "ACTIVE")
    log = AuditLog.objects.get(action="organization.created")
    assert (log.actor, str(log.organization_id)) == (user, body["id"])


def test_clients_cannot_set_server_controlled_fields(api_as):
    response = api_as(UserFactory()).post(
        URL,
        {"name": "Example Labs", "verification_status": "VERIFIED", "slug": "admin", "status": "X"},
    )

    organization = Organization.objects.get(pk=response.json()["id"])
    assert (organization.verification_status, organization.slug, organization.status) == (
        "UNVERIFIED",
        "example-labs",
        "ACTIVE",
    )


def test_organizations_with_the_same_name_get_distinct_slugs(api_as):
    client = api_as(UserFactory())

    slugs = [client.post(URL, {"name": "Example Labs"}).json()["slug"] for _ in range(3)]

    assert slugs[0] == "example-labs"
    assert len(set(slugs)) == 3
    assert all(slug.startswith("example-labs") for slug in slugs)


def test_creating_requires_a_verified_account(api, api_as):
    anonymous = api.post(URL, {"name": "Example Labs"})
    unverified = api_as(UserFactory(unverified=True)).post(URL, {"name": "Example Labs"})

    assert anonymous.status_code == 401
    assert (unverified.status_code, unverified.json()["code"]) == (403, "email_not_verified")
    assert not Organization.objects.exists()


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "!!!"}, "name"),
        ({"name": "x" * 121}, "name"),
        ({"name": "Example Labs", "country_code": "IND"}, "country_code"),
        ({"name": "Example Labs", "website": "not a url"}, "website"),
    ],
)
def test_create_validates_input(api_as, body, field):
    response = api_as(UserFactory()).post(URL, body)

    assert response.status_code == 400
    assert list(response.json()["errors"]) == [field]


def test_creating_organizations_is_rate_limited(api_as, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "organization_create", "1/day")
    client = api_as(UserFactory())

    assert client.post(URL, {"name": "First"}).status_code == 201
    assert client.post(URL, {"name": "Second"}).status_code == 429
    assert client.get(URL).status_code == 200


# --- Browse and view --------------------------------------------------------------------


def test_anyone_can_browse_active_organizations(api):
    OrganizationFactory(name="Example Labs")
    OrganizationFactory(name="Kochi Devs")
    OrganizationFactory(name="Hidden Co", status="SUSPENDED")

    everything = api.get(URL).json()["results"]
    searched = api.get(URL, {"q": "exam"}).json()["results"]
    typo = api.get(URL, {"q": "exmaple labs"}).json()["results"]

    assert {o["name"] for o in everything} == {"Example Labs", "Kochi Devs"}
    assert [o["name"] for o in searched] == ["Example Labs"]
    assert [o["name"] for o in typo] == ["Example Labs"]
    assert "viewer" not in everything[0]


def test_list_counts_only_active_members_in_a_fixed_number_of_queries(
    api, django_assert_max_num_queries
):
    for _ in range(5):
        organization, _ = organization_with_roles("ADMIN", "MEMBER")
        MemberFactory(organization=organization, status="LEFT")

    with django_assert_max_num_queries(2):
        results = api.get(URL).json()["results"]

    assert [o["member_count"] for o in results] == [3] * 5


def test_detail_shows_what_the_viewer_may_do(api, api_as):
    organization, members = organization_with_roles("ADMIN", "RECRUITER")

    anonymous = api.get(detail(organization)).json()["viewer"]
    admin = api_as(members["ADMIN"].user).get(detail(organization)).json()["viewer"]
    recruiter = api_as(members["RECRUITER"].user).get(detail(organization)).json()["viewer"]

    assert anonymous == {
        "membership_id": None,
        "role": None,
        "is_public": None,
        "can_manage": False,
        "assignable_roles": [],
    }
    assert (admin["role"], admin["can_manage"]) == ("ADMIN", True)
    assert admin["assignable_roles"] == ["MEMBER", "RECRUITER"]
    assert admin["membership_id"] == str(members["ADMIN"].pk)
    assert (recruiter["can_manage"], recruiter["assignable_roles"]) == (False, [])


def test_former_members_are_treated_as_outsiders(api_as):
    organization, _ = organization_with_roles()
    former = MemberFactory(organization=organization, role="ADMIN", status="REMOVED")

    viewer = api_as(former.user).get(detail(organization)).json()["viewer"]

    assert (viewer["role"], viewer["can_manage"]) == (None, False)


def test_suspended_organizations_are_visible_only_to_members_and_staff(api, api_as):
    organization, members = organization_with_roles()
    Organization.objects.filter(pk=organization.pk).update(status="SUSPENDED")

    assert api.get(detail(organization)).status_code == 404
    assert api_as(UserFactory()).get(detail(organization)).status_code == 404
    assert api_as(members["OWNER"].user).get(detail(organization)).status_code == 200
    moderator = UserFactory(platform_role="MODERATOR")
    assert api_as(moderator).get(detail(organization)).status_code == 200


def test_unknown_organization_is_not_found(api):
    assert api.get(f"{URL}{uuid.uuid7()}/").status_code == 404


def test_mine_lists_only_active_memberships(api, api_as):
    user = UserFactory()
    active = MemberFactory(user=user, role="RECRUITER")
    MemberFactory(user=user, status="LEFT")
    MemberFactory()  # someone else's

    mine = api_as(user).get(f"{URL}mine/").json()

    assert [(m["organization"]["id"], m["role"]) for m in mine] == [
        (str(active.organization_id), "RECRUITER")
    ]
    assert api.get(f"{URL}mine/").status_code == 401


# --- Edit -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "status"),
    [
        ("OWNER", 200),
        ("ADMIN", 200),
        ("RECRUITER", 403),
        ("MEMBER", 403),
        ("outsider", 403),
        ("anonymous", 401),
    ],
)
def test_only_owners_and_admins_can_edit(api, api_as, who, status):
    organization, members = organization_with_roles("ADMIN", "RECRUITER", "MEMBER")

    response = client_for(api_as, api, members, who).patch(
        detail(organization), {"description": "We build things."}
    )

    assert response.status_code == status
    organization.refresh_from_db()
    assert organization.description == ("We build things." if status == 200 else "")


def test_editing_is_audited_and_keeps_the_slug(api_as):
    organization, members = organization_with_roles()
    slug = organization.slug

    response = api_as(members["OWNER"].user).patch(
        detail(organization), {"name": "Renamed Labs", "city": "Kochi"}
    )

    assert (response.json()["name"], response.json()["slug"]) == ("Renamed Labs", slug)
    log = AuditLog.objects.get(action="organization.updated")
    assert log.metadata == {"fields": ["city", "name"]}
    assert log.organization_id == organization.pk


def test_a_suspended_organization_cannot_be_edited(api_as):
    organization, members = organization_with_roles()
    Organization.objects.filter(pk=organization.pk).update(status="SUSPENDED")

    response = api_as(members["OWNER"].user).patch(detail(organization), {"city": "Kochi"})

    assert (response.status_code, response.json()["code"]) == (422, "organization_suspended")
