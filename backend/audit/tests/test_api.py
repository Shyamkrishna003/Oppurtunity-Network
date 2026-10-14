"""Reading the audit trail: all of it for platform admins, a chosen part for a tenant's owners."""

import uuid

import pytest

from audit.models import AuditLog
from audit.services import record
from communities.tests.factories import CommunityMemberFactory, community_with_roles
from opportunities.tests.factories import distribute, make_job
from organizations.tests.factories import organization_with_roles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

ALL = "/api/v1/admin/audit-logs/"


def admin():
    return UserFactory.create(platform_role="ADMIN")


def actions(response) -> list[str]:
    assert response.status_code == 200, response.json()
    return [row["action"] for row in response.json()["results"]]


# --- The whole trail --------------------------------------------------------------------


def test_the_whole_trail_is_for_platform_admins_only(api, api_as):
    assert api.get(ALL).status_code == 401
    assert api_as(UserFactory.create()).get(ALL).status_code == 403
    assert api_as(UserFactory.create(platform_role="MODERATOR")).get(ALL).status_code == 403
    assert api_as(admin()).get(ALL).status_code == 200


def test_a_record_says_who_did_what_to_what_and_from_where(api_as):
    actor = UserFactory.create()
    actor.profile.display_name = "Ada Lovelace"
    actor.profile.save()
    target = UserFactory.create()
    record(action="user.something", target=target, actor=actor, metadata={"from": "A", "to": "B"})
    record(action="opportunity.expired", target=target)  # the system's doing

    newest, oldest = api_as(admin()).get(ALL).json()["results"]

    assert oldest["action"] == "user.something"
    assert oldest["actor"] == {"id": str(actor.pk), "display_name": "Ada Lovelace"}
    assert (oldest["actor_type"], oldest["target_type"]) == ("USER", "users.user")
    assert oldest["target_id"] == str(target.pk)
    assert oldest["metadata"] == {"from": "A", "to": "B"}
    assert {"ip", "request_id", "organization_id", "community_id"} <= set(oldest)
    assert (newest["actor"], newest["actor_type"]) == (None, "SYSTEM")


def test_the_trail_can_be_narrowed(api_as):
    ada, grace = UserFactory.create(email="ada@example.com"), UserFactory.create()
    organization, _ = organization_with_roles()
    community, _ = community_with_roles()
    record(action="user.logged_in", target=ada, actor=ada)
    record(action="report.filed", target=grace, actor=ada)
    record(action="report.resolved", target=grace, actor=grace, community_id=community.pk)
    record(
        action="organization.updated", target=organization, actor=grace,
        organization_id=organization.pk,
    )  # fmt: skip
    client = api_as(admin())

    def found(**params) -> set[str]:
        return set(actions(client.get(ALL, params)))

    assert found(actor=str(ada.pk)) == {"user.logged_in", "report.filed"}
    assert found(actor_email="Ada@Example.com ") == {"user.logged_in", "report.filed"}
    assert found(actor_email="nobody@example.com") == set()
    assert found(action="report.") == {"report.filed", "report.resolved"}
    assert found(action="report.filed") == {"report.filed"}
    assert found(target_type="users.user", target_id=str(grace.pk)) == {
        "report.filed",
        "report.resolved",
    }
    assert found(organization_id=str(organization.pk)) == {"organization.updated"}
    assert found(community_id=str(community.pk)) == {"report.resolved"}
    assert found(actor=str(ada.pk), action="report.") == {"report.filed"}
    assert found(target_id=str(uuid.uuid4())) == set()

    refused = client.get(ALL, {"target_id": "not-an-id"})
    assert refused.status_code == 400
    assert "target_id" in refused.json()["errors"]


def test_the_trail_is_newest_first_in_pages_with_a_fixed_number_of_queries(
    api_as, django_assert_max_num_queries
):
    target = UserFactory.create()
    for number in range(25):
        record(action=f"test.step_{number:02}", target=target, actor=UserFactory.create())
    client = api_as(admin())

    with django_assert_max_num_queries(3):
        first = client.get(ALL)

    page = first.json()
    assert len(page["results"]) == 20
    assert page["results"][0]["action"] == "test.step_24"
    rest = client.get(page["next"]).json()
    assert [row["action"] for row in rest["results"]][-1] == "test.step_00"
    assert rest["next"] is None


def test_the_trail_cannot_be_written_through_the_api(api_as):
    record(action="user.logged_in", target=UserFactory.create())
    client = api_as(admin())

    for method in (client.post, client.put, client.patch, client.delete):
        assert method(ALL, {}).status_code == 405
    assert AuditLog.objects.count() == 1


# --- An organization's own trail --------------------------------------------------------


def org_trail(organization) -> str:
    return f"/api/v1/organizations/{organization.pk}/audit-logs/"


def test_an_organizations_trail_is_for_its_owners(api, api_as):
    organization, members = organization_with_roles("ADMIN", "RECRUITER", "MEMBER")
    url = org_trail(organization)

    assert api.get(url).status_code == 401
    for role in ("ADMIN", "RECRUITER", "MEMBER"):
        assert api_as(members[role].user).get(url).status_code == 403
    assert api_as(UserFactory.create()).get(url).status_code == 403
    # Running the platform is not owning the organization; admins have their own view.
    assert api_as(admin()).get(url).status_code == 403
    assert api_as(members["OWNER"].user).get(url).status_code == 200
    unknown = f"/api/v1/organizations/{uuid.uuid4()}/audit-logs/"
    assert api_as(members["OWNER"].user).get(unknown).status_code == 404


def test_an_organizations_trail_shows_its_own_business_and_nothing_else(api_as):
    organization, members = organization_with_roles()
    other, _ = organization_with_roles()
    someone = UserFactory.create()
    job = make_job(status="PUBLISHED", organization=organization)

    def filed(action, target=job, where=organization, **metadata):
        record(
            action=action, target=target, actor=someone, organization_id=where.pk,
            metadata=metadata,
        )  # fmt: skip

    filed("organization.role_changed", target=organization)
    filed("opportunity.published")
    filed("application.status_changed", **{"from": "APPLIED", "to": "INTERVIEW"})
    filed("event.checked_in")
    # Who asked whom for a referral is theirs alone until a referral is made.
    filed("referral.requested")
    filed("referral.declined")
    # Which moderator acted is not for the organization to know.
    filed("moderation.action_taken")
    filed("organization.updated", target=other, where=other)

    response = api_as(members["OWNER"].user).get(org_trail(organization))

    assert set(actions(response)) == {
        "organization.role_changed",
        "opportunity.published",
        "application.status_changed",
        "event.checked_in",
    }
    row = response.json()["results"][0]
    assert not {"ip", "request_id", "organization_id", "community_id"} & set(row)


# --- A community's own trail ------------------------------------------------------------


def community_trail(community) -> str:
    return f"/api/v1/communities/{community.pk}/audit-logs/"


def test_a_communitys_trail_is_for_its_owners(api, api_as):
    community, members = community_with_roles("ADMIN", "MODERATOR", "MEMBER")
    url = community_trail(community)

    assert api.get(url).status_code == 401
    for role in ("ADMIN", "MODERATOR", "MEMBER"):
        assert api_as(members[role].user).get(url).status_code == 403
    assert api_as(UserFactory.create()).get(url).status_code == 403
    assert api_as(admin()).get(url).status_code == 403
    assert api_as(members["OWNER"].user).get(url).status_code == 200

    private, _ = community_with_roles(visibility="PRIVATE")
    assert api_as(UserFactory.create()).get(community_trail(private)).status_code == 404


def test_a_communitys_trail_covers_its_moderation_but_never_names_a_reporter(api_as):
    community, members = community_with_roles("MODERATOR")
    reporter = CommunityMemberFactory.create(community=community).user
    job = make_job(status="PUBLISHED")
    distribute(job, community)
    filed = api_as(reporter).post(
        "/api/v1/reports/",
        {
            "target_type": "OPPORTUNITY",
            "target_id": str(job.pk),
            "category": "SCAM",
            "community_id": str(community.pk),
        },
    )
    assert filed.status_code == 201
    report = f"/api/v1/communities/{community.pk}/reports/{filed.json()['id']}/"
    moderator = api_as(members["MODERATOR"].user)
    assert moderator.post(f"{report}claim/").status_code == 200
    assert moderator.post(f"{report}remove/", {"reason": "Scam."}).status_code == 200
    # Something the platform did to the community itself.
    record(
        action="moderation.action_taken", target=community, actor=admin(),
        community_id=community.pk,
    )  # fmt: skip

    response = api_as(members["OWNER"].user).get(community_trail(community))

    assert actions(response) == ["report.resolved", "opportunity.share_reviewed", "report.claimed"]
    assert str(reporter.pk) not in response.content.decode()
    who = {row["actor"]["id"] for row in response.json()["results"]}
    assert who == {str(members["MODERATOR"].user.pk)}
