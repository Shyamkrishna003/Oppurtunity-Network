import threading
import uuid

import pytest
from django.db import connection

from audit.models import AuditLog
from communities.models import Community
from communities.tests.factories import (
    CommunityFactory,
    CommunityMemberFactory,
    community_with_roles,
)
from opportunities import distribution
from opportunities.models import Opportunity, OpportunityCommunity
from opportunities.tests.factories import distribute, make_job
from organizations.tests.factories import organization_with_roles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

OPPORTUNITIES = "/api/v1/opportunities/"
COMMUNITIES = "/api/v1/communities/"


def shares_url(job, *parts) -> str:
    return "/".join([f"{OPPORTUNITIES}{job.pk}/communities", *map(str, parts), ""])


def community_url(community, *parts) -> str:
    return "/".join([f"{COMMUNITIES}{community.pk}", *map(str, parts), ""])


def share(api_as, user, job, *communities):
    return api_as(user).post(shares_url(job), {"community_ids": [str(c.pk) for c in communities]})


def listed(client, community, **params) -> list[str]:
    """IDs of the opportunities a community shows to this client."""
    results = client.get(community_url(community, "opportunities"), params).json()["results"]
    return [item["opportunity"]["id"] for item in results]


def status_in(job, community):
    row = OpportunityCommunity.objects.filter(opportunity=job, community=community).first()
    return row.status if row else None


@pytest.fixture
def scene():
    """A published job whose poster is an ordinary member of a review-first community."""
    community, members = community_with_roles("ADMIN", "MODERATOR", "MEMBER")
    poster = members["MEMBER"].user
    job = make_job(status="PUBLISHED", creator=poster)
    return job, community, members, poster


# --- Sharing ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("posting_policy", "role", "outcome"),
    [
        ("MEMBERS_WITH_APPROVAL", "MEMBER", "PENDING"),
        ("MEMBERS_WITH_APPROVAL", "MODERATOR", "APPROVED"),
        ("MEMBERS_AUTO", "MEMBER", "APPROVED"),
        ("ADMINS_ONLY", "ADMIN", "APPROVED"),
    ],
)
def test_sharing_follows_the_communitys_posting_policy(api, api_as, posting_policy, role, outcome):
    community, members = community_with_roles(role, posting_policy=posting_policy)
    poster = members[role].user
    job = make_job(status="PUBLISHED", creator=poster)

    response = share(api_as, poster, job, community)

    assert response.status_code == 200
    (row,) = response.json()
    assert (row["community"]["id"], row["status"]) == (str(community.pk), outcome)
    assert listed(api, community) == ([str(job.pk)] if outcome == "APPROVED" else [])
    log = AuditLog.objects.get(action="opportunity.shared")
    assert (log.community_id, log.metadata["status"]) == (community.pk, outcome)


@pytest.mark.parametrize(
    ("posting_policy", "role"), [("ADMINS_ONLY", "MEMBER"), ("ADMINS_ONLY", "MODERATOR")]
)
def test_a_community_can_keep_sharing_to_its_admins(api_as, posting_policy, role):
    community, members = community_with_roles(role, posting_policy=posting_policy)
    job = make_job(status="PUBLISHED", creator=members[role].user)

    response = share(api_as, members[role].user, job, community)

    assert (response.status_code, response.json()["code"]) == (422, "cannot_share")
    assert response.json()["errors"] == {
        str(community.pk): ["This community does not let you share opportunities."]
    }


def test_sharing_is_all_or_nothing_and_says_why_for_each_community(api_as, scene):
    job, community, _, poster = scene
    not_mine = CommunityFactory()
    private = CommunityFactory(visibility="PRIVATE")

    response = share(api_as, poster, job, community, not_mine, private)

    assert response.status_code == 422
    # A private community the poster is not in is answered exactly like any other.
    message = ["You are not a member of this community."]
    assert response.json()["errors"] == {str(not_mine.pk): message, str(private.pk): message}
    assert not OpportunityCommunity.objects.exists()


@pytest.mark.parametrize("status", ["PENDING", "INVITED", "LEFT", "BANNED"])
def test_only_active_members_can_share(api_as, status):
    community = CommunityFactory(posting_policy="MEMBERS_AUTO")
    poster = CommunityMemberFactory(community=community, status=status).user
    job = make_job(status="PUBLISHED", creator=poster)

    assert share(api_as, poster, job, community).status_code == 422
    assert status_in(job, community) is None


def test_sharing_needs_a_published_opportunity_and_its_manager(api, api_as, scene):
    job, community, members, poster = scene
    draft = make_job(creator=poster)
    closed = make_job(status="CLOSED", creator=poster)

    for unpublished in (draft, closed):
        response = share(api_as, poster, unpublished, community)
        assert (response.status_code, response.json()["code"]) == (422, "not_published")
    # An admin of the community, but not a manager of the job.
    assert share(api_as, members["ADMIN"].user, job, community).status_code == 403
    assert api.post(shares_url(job), {"community_ids": [str(community.pk)]}).status_code == 401
    assert not OpportunityCommunity.objects.exists()


def test_share_request_is_validated(api_as, scene):
    job, _, _, poster = scene
    client = api_as(poster)

    assert client.post(shares_url(job), {"community_ids": []}).status_code == 400
    assert client.post(shares_url(job), {}).status_code == 400
    too_many = [str(uuid.uuid7()) for _ in range(11)]
    assert client.post(shares_url(job), {"community_ids": too_many}).status_code == 400


def test_sharing_again_changes_nothing(api_as, scene):
    job, community, _, poster = scene

    first = share(api_as, poster, job, community)
    second = share(api_as, poster, job, community)

    assert first.json() == second.json()
    assert OpportunityCommunity.objects.count() == 1
    assert AuditLog.objects.filter(action="opportunity.shared").count() == 1


def test_an_organizations_recruiter_shares_into_their_own_communities(api_as):
    organization, org_members = organization_with_roles("RECRUITER")
    recruiter = org_members["RECRUITER"].user
    job = make_job(status="PUBLISHED", creator=org_members["OWNER"].user, organization=organization)
    community = CommunityFactory(posting_policy="MEMBERS_AUTO")
    CommunityMemberFactory(community=community, user=recruiter)

    response = share(api_as, recruiter, job, community)

    assert response.status_code == 200
    log = AuditLog.objects.get(action="opportunity.shared")
    assert (log.organization_id, log.community_id) == (organization.pk, community.pk)


def test_share_options_show_what_would_happen_in_each_of_my_communities(api_as):
    poster = UserFactory()
    job = make_job(status="PUBLISHED", creator=poster)
    review = CommunityFactory(name="A review")
    auto = CommunityFactory(name="B auto", posting_policy="MEMBERS_AUTO")
    closed = CommunityFactory(name="C admins", posting_policy="ADMINS_ONLY")
    already = CommunityFactory(name="D already")
    for community in (review, auto, closed, already):
        CommunityMemberFactory(community=community, user=poster)
    CommunityMemberFactory(user=poster, status="PENDING")  # not a member yet: not offered
    distribute(job, already, status="REJECTED")

    options = api_as(poster).get(shares_url(job, "options")).json()

    assert [(o["community"]["name"], o["current"], o["outcome"]) for o in options] == [
        ("A review", None, "PENDING"),
        ("B auto", None, "APPROVED"),
        ("C admins", None, None),
        ("D already", "REJECTED", "PENDING"),
    ]
    assert api_as(UserFactory()).get(shares_url(job, "options")).status_code == 403


# --- Review -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "status"),
    [("OWNER", 200), ("ADMIN", 200), ("MODERATOR", 200), ("MEMBER", 403), ("outsider", 403)],
)
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_who_may_review_a_share(api_as, scene, who, status, action):
    job, community, members, _ = scene
    pending = distribute(job, community, status="PENDING")
    # The poster is the community's MEMBER, so use a different ordinary member here.
    actors = {**{role: m.user for role, m in members.items()}, "outsider": UserFactory()}
    actors["MEMBER"] = CommunityMemberFactory(community=community).user

    response = api_as(actors[who]).post(community_url(community, "submissions", pending.pk, action))

    assert response.status_code == status
    decided = {"approve": "APPROVED", "reject": "REJECTED"}[action]
    assert status_in(job, community) == (decided if status == 200 else "PENDING")


def test_approval_puts_the_opportunity_in_the_communitys_list(api, api_as, scene):
    job, community, members, poster = scene
    pending_id = OpportunityCommunity.objects.get(
        pk=share(api_as, poster, job, community).json()[0]["id"]
    ).pk
    moderator = api_as(members["MODERATOR"].user)
    assert listed(api, community) == []

    approved = moderator.post(community_url(community, "submissions", pending_id, "approve"))
    again = moderator.post(community_url(community, "submissions", pending_id, "approve"))

    assert approved.status_code == again.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["submitted_by"]["id"] == str(poster.pk)
    assert listed(api, community) == [str(job.pk)]
    log = AuditLog.objects.get(action="opportunity.share_reviewed")
    assert (log.metadata["from"], log.metadata["to"]) == ("PENDING", "APPROVED")
    assert log.actor == members["MODERATOR"].user


def test_rejection_gives_the_poster_a_reason_and_allows_another_try(api_as, scene):
    job, community, members, poster = scene
    share_id = share(api_as, poster, job, community).json()[0]["id"]
    moderator = api_as(members["MODERATOR"].user)

    moderator.post(
        community_url(community, "submissions", share_id, "reject"), {"reason": "Off topic."}
    )
    seen_by_poster = api_as(poster).get(shares_url(job)).json()
    resubmitted = share(api_as, poster, job, community).json()

    assert (seen_by_poster[0]["status"], seen_by_poster[0]["rejection_reason"]) == (
        "REJECTED",
        "Off topic.",
    )
    assert (resubmitted[0]["status"], resubmitted[0]["rejection_reason"]) == ("PENDING", "")
    assert resubmitted[0]["id"] == share_id  # the same row, offered again


def test_a_reviewer_can_reconsider_a_rejection(api, api_as, scene):
    job, community, members, _ = scene
    rejected = distribute(job, community, status="REJECTED", rejection_reason="Off topic.")

    response = api_as(members["ADMIN"].user).post(
        community_url(community, "submissions", rejected.pk, "approve")
    )

    assert (response.status_code, response.json()["status"]) == (200, "APPROVED")
    assert response.json()["rejection_reason"] == ""
    assert listed(api, community) == [str(job.pk)]


def test_removal_is_final_and_takes_it_out_of_the_list(api, api_as, scene):
    job, community, members, poster = scene
    approved = distribute(job, community, is_featured=True)
    admin = api_as(members["ADMIN"].user)

    removed = admin.post(community_url(community, "submissions", approved.pk, "remove"))

    assert (removed.json()["status"], removed.json()["is_featured"]) == ("REMOVED", False)
    assert listed(api, community) == []
    again = share(api_as, poster, job, community)
    assert again.json()["errors"] == {
        str(community.pk): ["This community has removed this opportunity."]
    }
    withdrawn = api_as(poster).delete(shares_url(job, community.pk))
    assert (withdrawn.status_code, withdrawn.json()["code"]) == (409, "removed_by_community")
    assert status_in(job, community) == "REMOVED"


def test_one_communitys_decision_does_not_affect_another(api, api_as):
    poster = UserFactory()
    job = make_job(status="PUBLISHED", creator=poster)
    first, first_members = community_with_roles()
    second, _ = community_with_roles()
    rejected_here = distribute(job, first, status="PENDING")
    distribute(job, second)

    api_as(first_members["OWNER"].user).post(
        community_url(first, "submissions", rejected_here.pk, "reject")
    )

    assert listed(api, first) == []
    assert listed(api, second) == [str(job.pk)]
    assert api.get(f"{OPPORTUNITIES}{job.pk}/").status_code == 200  # still public


def test_shares_of_one_community_cannot_be_reached_through_another(api_as, scene):
    job, community, _, _ = scene
    theirs = distribute(job, community, status="PENDING")
    mine, my_members = community_with_roles()
    owner = api_as(my_members["OWNER"].user)

    for action in ("approve", "reject", "remove", "feature", "unfeature"):
        assert owner.post(community_url(mine, "submissions", theirs.pk, action)).status_code == 404
    assert owner.post(community_url(mine, "submissions", theirs.pk, "delete")).status_code == 404
    assert status_in(job, community) == "PENDING"


def test_a_suspended_community_cannot_review(api_as, scene):
    job, community, members, _ = scene
    pending = distribute(job, community, status="PENDING")
    Community.objects.filter(pk=community.pk).update(status="SUSPENDED")

    response = api_as(members["OWNER"].user).post(
        community_url(community, "submissions", pending.pk, "approve")
    )

    assert (response.status_code, response.json()["code"]) == (422, "community_suspended")


@pytest.mark.parametrize("action", ["remove", "ban"])
def test_expelling_a_member_rejects_what_they_had_waiting(api_as, scene, action):
    job, community, members, poster = scene
    other_job = make_job(status="PUBLISHED", creator=poster)
    waiting = distribute(job, community, status="PENDING", submitted_by=poster)
    shown = distribute(other_job, community, submitted_by=poster)

    response = api_as(members["OWNER"].user).post(
        community_url(community, "members", members["MEMBER"].pk, action)
    )

    assert response.status_code == 200
    waiting.refresh_from_db()
    shown.refresh_from_db()
    assert waiting.status == "REJECTED"
    assert "no longer in the community" in waiting.rejection_reason
    assert shown.status == "APPROVED"  # what the community already accepted stays


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_approving_and_rejecting_one_share_at_once_are_applied_in_order():
    community, members = community_with_roles("ADMIN")
    pending = distribute(make_job(status="PUBLISHED"), community, status="PENDING")
    barrier = threading.Barrier(2)
    failures = []

    def run(reviewer, decision):
        barrier.wait()
        try:
            distribution.review(
                actor=reviewer, community_id=community.pk, share_id=pending.pk, decision=decision
            )
        except Exception as exc:
            failures.append(exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(members["OWNER"].user, "APPROVED")),
        threading.Thread(target=run, args=(members["ADMIN"].user, "REJECTED")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    pending.refresh_from_db()
    trail = [
        (log.metadata["from"], log.metadata["to"])
        for log in AuditLog.objects.filter(action="opportunity.share_reviewed").order_by(
            "created_at"
        )
    ]
    # The lock makes the two decisions happen one after the other, and the record shows a
    # real sequence either way. Approval first: the rejection no longer applies. Rejection
    # first: the approval reverses it, which a reviewer is allowed to do.
    assert pending.status == "APPROVED"
    assert (trail, len(failures)) in (
        ([("PENDING", "APPROVED")], 1),
        ([("PENDING", "REJECTED"), ("REJECTED", "APPROVED")], 0),
    )


# --- Featuring --------------------------------------------------------------------------


def test_featuring_pins_an_approved_opportunity(api, api_as, scene):
    job, community, members, poster = scene
    other = make_job(status="PUBLISHED", creator=poster)
    pinned = distribute(job, community)
    distribute(other, community)
    moderator = api_as(members["MODERATOR"].user)

    featured = moderator.post(community_url(community, "submissions", pinned.pk, "feature"))
    moderator.post(community_url(community, "submissions", pinned.pk, "feature"))

    assert featured.json()["is_featured"] is True
    assert listed(api, community, featured="true") == [str(job.pk)]
    assert set(listed(api, community)) == {str(job.pk), str(other.pk)}
    assert AuditLog.objects.filter(action="opportunity.share_featured").count() == 1

    unfeatured = moderator.post(community_url(community, "submissions", pinned.pk, "unfeature"))
    assert unfeatured.json()["is_featured"] is False
    assert listed(api, community, featured="true") == []


def test_only_approved_shares_can_be_featured_and_only_by_reviewers(api_as, scene):
    job, community, members, _ = scene
    pending = distribute(job, community, status="PENDING")
    feature = community_url(community, "submissions", pending.pk, "feature")

    not_approved = api_as(members["OWNER"].user).post(feature)
    not_a_reviewer = api_as(UserFactory()).post(feature)

    assert (not_approved.status_code, not_approved.json()["code"]) == (409, "invalid_transition")
    assert not_a_reviewer.status_code == 403


# --- The community's list and queue -----------------------------------------------------


@pytest.mark.parametrize(
    ("share_status", "job_fields", "shown"),
    [
        ("APPROVED", {}, True),
        ("PENDING", {}, False),
        ("REJECTED", {}, False),
        ("REMOVED", {}, False),
        ("APPROVED", {"status": "CLOSED"}, False),
        ("APPROVED", {"status": "EXPIRED"}, False),
        ("APPROVED", {"status": "ARCHIVED"}, False),
        ("APPROVED", {"moderation_status": "HIDDEN"}, False),
    ],
)
def test_a_communitys_list_shows_only_open_approved_opportunities(
    api, share_status, job_fields, shown
):
    community = CommunityFactory()
    job = make_job(**{"status": "PUBLISHED", **job_fields})
    distribute(job, community, status=share_status)

    assert listed(api, community) == ([str(job.pk)] if shown else [])


def test_community_approval_does_not_override_who_may_see_the_opportunity(api, api_as):
    organization, org_members = organization_with_roles("MEMBER")
    community, members = community_with_roles("MEMBER")
    internal = make_job(
        status="PUBLISHED",
        visibility="ORGANIZATION",
        creator=org_members["OWNER"].user,
        organization=organization,
    )
    for_members = make_job(status="PUBLISHED", visibility="COMMUNITY")
    distribute(internal, community)
    distribute(for_members, community)

    assert listed(api, community) == []
    assert listed(api_as(members["MEMBER"].user), community) == [str(for_members.pk)]
    assert listed(api_as(org_members["MEMBER"].user), community) == [str(internal.pk)]


def test_a_private_communitys_list_is_for_its_members(api, api_as):
    community, members = community_with_roles(visibility="PRIVATE")
    job = make_job(status="PUBLISHED")
    distribute(job, community)

    assert api.get(community_url(community, "opportunities")).status_code == 404
    assert api_as(UserFactory()).get(community_url(community, "opportunities")).status_code == 404
    assert listed(api_as(members["OWNER"].user), community) == [str(job.pk)]


def test_community_list_uses_a_fixed_number_of_queries(api, django_assert_max_num_queries):
    community = CommunityFactory()
    for _ in range(8):
        distribute(make_job(status="PUBLISHED", skills=("Python", "Django")), community)

    with django_assert_max_num_queries(4):
        assert len(listed(api, community)) == 8


def test_the_review_queue_is_for_reviewers_and_filters_by_state(api, api_as, scene):
    job, community, members, poster = scene
    distribute(job, community, status="PENDING", submitted_by=poster)
    distribute(make_job(status="PUBLISHED"), community, status="REJECTED")
    queue = community_url(community, "submissions")
    moderator = api_as(members["MODERATOR"].user)

    pending = moderator.get(queue).json()["results"]
    rejected = moderator.get(queue, {"status": "REJECTED"}).json()["results"]

    assert [(s["status"], s["opportunity"]["id"]) for s in pending] == [("PENDING", str(job.pk))]
    assert pending[0]["submitted_by"]["id"] == str(poster.pk)
    assert [s["status"] for s in rejected] == ["REJECTED"]
    assert moderator.get(queue, {"status": "MAYBE"}).status_code == 400
    assert api_as(poster).get(queue).status_code == 403  # an ordinary member
    assert api.get(queue).status_code == 401


# --- The opportunity's side -------------------------------------------------------------


def test_withdrawing_takes_the_opportunity_back(api, api_as, scene):
    job, community, members, poster = scene
    distribute(job, community)
    client = api_as(poster)

    assert api_as(members["OWNER"].user).delete(shares_url(job, community.pk)).status_code == 403
    assert client.delete(shares_url(job, community.pk)).status_code == 204
    assert client.delete(shares_url(job, community.pk)).status_code == 404
    assert listed(api, community) == []
    assert client.get(shares_url(job)).json() == []
    assert AuditLog.objects.filter(action="opportunity.share_withdrawn").count() == 1


def test_a_community_only_job_reaches_members_once_approved(api_as, scene):
    _, community, members, poster = scene
    job = make_job(status="PUBLISHED", visibility="COMMUNITY", creator=poster)
    fellow = api_as(CommunityMemberFactory(community=community).user)
    url = f"{OPPORTUNITIES}{job.pk}/"
    share_id = share(api_as, poster, job, community).json()[0]["id"]
    assert fellow.get(url).status_code == 404  # waiting for review

    api_as(members["OWNER"].user).post(community_url(community, "submissions", share_id, "approve"))

    assert fellow.get(url).status_code == 200
    assert api_as(UserFactory()).get(url).status_code == 404


def test_the_job_page_names_the_communities_showing_it_without_leaking_private_ones(api, api_as):
    job = make_job(status="PUBLISHED")
    public = CommunityFactory(name="Kochi Developers")
    private, private_members = community_with_roles(name="Secret Circle", visibility="PRIVATE")
    waiting = CommunityFactory(name="Still Reviewing")
    distribute(job, public)
    distribute(job, private)
    distribute(job, waiting, status="PENDING")
    url = f"{OPPORTUNITIES}{job.pk}/"

    def names(client):
        return sorted(c["name"] for c in client.get(url).json()["communities"])

    assert names(api) == ["Kochi Developers"]
    assert names(api_as(private_members["OWNER"].user)) == ["Kochi Developers", "Secret Circle"]
    assert Opportunity.objects.get(pk=job.pk).distributions.count() == 3
