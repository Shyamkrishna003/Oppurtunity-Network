"""Who can see which opportunity: audience x lifecycle state x moderation x viewer."""

import pytest
from rest_framework.test import APIClient

from communities.tests.factories import CommunityMemberFactory, community_with_roles
from opportunities import selectors
from opportunities.models import Opportunity
from opportunities.tests.factories import distribute, make_job
from organizations.tests.factories import organization_with_roles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

VIEWERS = (
    "anonymous",
    "stranger",
    "community_member",
    "organization_member",
    "manager",
    "moderator",
)
EVERYONE = set(VIEWERS)
INSIDERS = {"manager", "moderator"}  # see it whatever its state


@pytest.fixture
def world(api, api_as):
    """An organization's job, shared with a community, and one viewer of every kind."""
    organization, org_members = organization_with_roles("RECRUITER", "MEMBER")
    community, community_members = community_with_roles("MEMBER")
    viewers = {
        "stranger": UserFactory(),
        "community_member": community_members["MEMBER"].user,
        "organization_member": org_members["MEMBER"].user,
        "manager": org_members["RECRUITER"].user,
        "moderator": UserFactory(platform_role="MODERATOR"),
    }

    def build(distribution="APPROVED", **fields):
        job = make_job(creator=org_members["OWNER"].user, organization=organization, **fields)
        if distribution:
            distribute(job, community, status=distribution)
        return job

    def who_sees(job) -> set[str]:
        clients: dict[str, APIClient] = {"anonymous": api}
        clients.update({name: api_as(user) for name, user in viewers.items()})
        url = f"/api/v1/opportunities/{job.pk}/"
        seen = {name for name, client in clients.items() if client.get(url).status_code == 200}
        # The list rule and the detail rule are one queryset; check they agree.
        for name, user in viewers.items():
            listed = selectors.visible_to(user).filter(pk=job.pk).exists()
            assert listed is (name in seen), name
        return seen

    return build, who_sees, viewers, community


@pytest.mark.parametrize(
    ("visibility", "expected"),
    [
        ("PUBLIC", EVERYONE),
        ("COMMUNITY", INSIDERS | {"community_member"}),
        ("ORGANIZATION", INSIDERS | {"organization_member"}),
    ],
)
def test_a_published_opportunity_reaches_its_audience(world, visibility, expected):
    build, who_sees, *_ = world

    assert who_sees(build(status="PUBLISHED", visibility=visibility)) == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("DRAFT", INSIDERS),
        ("PUBLISHED", EVERYONE),
        ("CLOSED", EVERYONE),
        ("EXPIRED", EVERYONE),
        ("ARCHIVED", INSIDERS),
    ],
)
def test_lifecycle_state_decides_whether_the_public_sees_it(world, status, expected):
    build, who_sees, *_ = world

    assert who_sees(build(status=status)) == expected


@pytest.mark.parametrize("moderation_status", ["HIDDEN", "REMOVED"])
def test_a_moderated_opportunity_is_seen_only_by_its_managers_and_staff(world, moderation_status):
    build, who_sees, *_ = world

    assert who_sees(build(status="PUBLISHED", moderation_status=moderation_status)) == INSIDERS


@pytest.mark.parametrize(
    ("distribution", "reaches_community"),
    [
        ("APPROVED", True),
        ("PENDING", False),
        ("REJECTED", False),
        ("REMOVED", False),
        (None, False),
    ],
)
def test_community_audience_needs_an_approved_share(world, distribution, reaches_community):
    build, who_sees, *_ = world

    seen = who_sees(build(status="PUBLISHED", visibility="COMMUNITY", distribution=distribution))

    assert ("community_member" in seen) is reaches_community
    assert seen - {"community_member"} == INSIDERS


@pytest.mark.parametrize("member_status", ["PENDING", "INVITED", "LEFT", "REMOVED", "BANNED"])
def test_community_audience_means_active_members_only(world, api_as, member_status):
    build, _, _, community = world
    job = build(status="PUBLISHED", visibility="COMMUNITY")
    not_active = CommunityMemberFactory(community=community, status=member_status).user

    assert api_as(not_active).get(f"/api/v1/opportunities/{job.pk}/").status_code == 404


def test_a_personal_draft_is_seen_only_by_its_creator_and_staff(api, api_as):
    draft = make_job()
    url = f"/api/v1/opportunities/{draft.pk}/"

    assert api_as(draft.creator).get(url).status_code == 200
    assert api_as(UserFactory(platform_role="ADMIN")).get(url).status_code == 200
    assert api_as(UserFactory()).get(url).status_code == 404
    assert api.get(url).status_code == 404


def test_hidden_missing_and_draft_look_the_same_from_outside(api):
    draft = make_job()
    hidden = make_job(status="PUBLISHED", moderation_status="HIDDEN")

    bodies = []
    for pk in (draft.pk, hidden.pk, "0199b7c0-0000-7000-8000-000000000000"):
        response = api.get(f"/api/v1/opportunities/{pk}/")
        assert response.status_code == 404
        body = response.json()
        body.pop("request_id")
        bodies.append(body)

    assert bodies[0] == bodies[1] == bodies[2]


def test_visibility_is_decided_in_one_query(django_assert_num_queries):
    user = UserFactory()
    for _ in range(3):
        make_job(status="PUBLISHED")

    total = Opportunity.objects.count()

    with django_assert_num_queries(1):
        assert selectors.visible_to(user).count() == total
