"""That the things which happen elsewhere in the system tell the right people."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from communities.tests.factories import CommunityMemberFactory, community_with_roles
from notifications.catalog import render
from notifications.models import Notification
from opportunities import services as opportunity_services
from opportunities.tests.factories import distribute, make_job
from organizations.tests.factories import organization_with_roles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def told(user) -> list[str]:
    """Types of the notifications a user received, oldest first."""
    return list(
        Notification.objects.filter(recipient=user)
        .order_by("created_at")
        .values_list("type", flat=True)
    )


def latest(user):
    return render(Notification.objects.filter(recipient=user).latest("created_at"))


def community_url(community, *parts) -> str:
    return "/".join([f"/api/v1/communities/{community.pk}", *map(str, parts), ""])


# --- Communities ------------------------------------------------------------------------


def test_a_request_to_join_reaches_the_reviewers_and_the_answer_reaches_the_person(api_as):
    community, members = community_with_roles(
        "ADMIN", "MODERATOR", "MEMBER", join_policy="APPROVAL", name="Kochi Developers"
    )
    applicant = UserFactory(display_name="Ada Lovelace")

    api_as(applicant).post(community_url(community, "join"))

    for role in ("OWNER", "ADMIN", "MODERATOR"):
        assert told(members[role].user) == ["COMMUNITY_JOIN_REQUESTED"]
    assert told(members["MEMBER"].user) == []  # ordinary members do not decide
    assert told(applicant) == []
    request = latest(members["OWNER"].user)
    assert request.title == "Ada Lovelace asked to join Kochi Developers"
    assert request.url == f"/communities/{community.pk}"

    member = community.memberships.get(user=applicant)
    api_as(members["ADMIN"].user).post(community_url(community, "members", member.pk, "approve"))

    assert told(applicant) == ["COMMUNITY_JOIN_APPROVED"]
    assert latest(applicant).title == "You are now a member of Kochi Developers"
    assert told(members["ADMIN"].user) == ["COMMUNITY_JOIN_REQUESTED"]  # not told of their own act


def test_joining_an_open_community_notifies_nobody(api_as):
    community, members = community_with_roles("ADMIN")

    api_as(UserFactory()).post(community_url(community, "join"))

    assert not Notification.objects.exists()


@pytest.mark.parametrize(
    ("action", "start", "expected"),
    [
        ("reject", "PENDING", "COMMUNITY_JOIN_REJECTED"),
        ("remove", "ACTIVE", "COMMUNITY_REMOVED"),
        ("ban", "ACTIVE", "COMMUNITY_REMOVED"),
    ],
)
def test_decisions_about_a_member_reach_that_member(api_as, action, start, expected):
    community, members = community_with_roles()
    member = CommunityMemberFactory(community=community, status=start)

    api_as(members["OWNER"].user).post(community_url(community, "members", member.pk, action))

    assert told(member.user) == [expected]


@pytest.mark.parametrize("action", ["leave"])
def test_what_a_person_does_themselves_is_not_announced_to_them(api_as, action):
    community, members = community_with_roles("MEMBER")

    api_as(members["MEMBER"].user).post(community_url(community, action))

    assert not Notification.objects.exists()


def test_a_community_invitation_is_shown_in_the_app_and_emailed_once(
    api_as, django_capture_on_commit_callbacks
):
    community, members = community_with_roles(name="Kochi Developers")
    owner = members["OWNER"].user
    invitee = UserFactory()

    with django_capture_on_commit_callbacks(execute=True):
        api_as(owner).post(community_url(community, "invitations"), {"user_id": str(invitee.pk)})

    assert told(invitee) == ["COMMUNITY_INVITATION"]
    invitation = latest(invitee)
    assert invitation.title == "You are invited to join Kochi Developers"
    assert owner.profile.display_name in invitation.body
    # The dedicated invitation email is the only one; the notification adds no second.
    assert [m.subject for m in mail.outbox] == ["You are invited to join Kochi Developers"]


# --- Organizations ----------------------------------------------------------------------


def organization_url(organization, *parts) -> str:
    return "/".join([f"/api/v1/organizations/{organization.pk}", *map(str, parts), ""])


def test_an_organization_invitation_appears_in_the_app_for_someone_with_an_account(api_as):
    organization, members = organization_with_roles()
    owner = api_as(members["OWNER"].user)
    existing = UserFactory()

    owner.post(
        organization_url(organization, "invitations"),
        {"email": existing.email, "role": "RECRUITER"},
    )
    owner.post(
        organization_url(organization, "invitations"),
        {"email": "new@example.com", "role": "MEMBER"},
    )

    assert told(existing) == ["ORGANIZATION_INVITATION"]
    invitation = latest(existing)
    assert invitation.title == f"You are invited to join {organization.name}"
    assert "as recruiter" in invitation.body
    # The link works, and its secret was derived, not stored.
    assert api_as(existing).get(f"/api/v1{invitation.url}/").status_code == 200
    stored = Notification.objects.get(recipient=existing)
    assert invitation.url.rsplit("/", 1)[-1] not in str(stored.payload)
    assert Notification.objects.count() == 1  # nothing for an address without an account


def test_an_unconfirmed_account_is_not_shown_an_invitation_sent_to_its_address(api_as):
    """The notification carries the invitation link, so it only goes to an account that has
    proved it owns the address."""
    organization, members = organization_with_roles()
    squatter = UserFactory(unverified=True)

    response = api_as(members["OWNER"].user).post(
        organization_url(organization, "invitations"),
        {"email": squatter.email, "role": "MEMBER"},
    )

    assert response.status_code == 201  # the invitation itself is unaffected
    assert told(squatter) == []


def test_role_changes_and_removal_reach_the_member(api_as):
    organization, members = organization_with_roles("MEMBER")
    owner = api_as(members["OWNER"].user)
    member = members["MEMBER"]

    owner.patch(organization_url(organization, "members", member.pk), {"role": "RECRUITER"})
    owner.delete(organization_url(organization, "members", member.pk))

    assert told(member.user) == ["ORGANIZATION_ROLE_CHANGED", "ORGANIZATION_REMOVED"]
    assert told(members["OWNER"].user) == []
    first = render(Notification.objects.filter(recipient=member.user).earliest("created_at"))
    assert first.body == "You are now recruiter there."


# --- Sharing opportunities --------------------------------------------------------------


@pytest.fixture
def shared(api_as):
    """A job its poster has just shared with a review-first community."""
    community, members = community_with_roles(
        "ADMIN", "MODERATOR", "MEMBER", name="Kochi Developers"
    )
    poster = members["MEMBER"].user
    job = make_job(status="PUBLISHED", creator=poster, title="Backend Engineer")
    response = api_as(poster).post(
        f"/api/v1/opportunities/{job.pk}/communities/", {"community_ids": [str(community.pk)]}
    )
    return job, community, members, poster, response.json()[0]["id"]


def test_a_share_waiting_for_review_reaches_the_reviewers(shared):
    job, community, members, poster, _ = shared

    for role in ("OWNER", "ADMIN", "MODERATOR"):
        assert told(members[role].user) == ["SHARE_SUBMITTED"]
    assert told(poster) == []
    waiting = latest(members["MODERATOR"].user)
    assert waiting.title == "“Backend Engineer” is waiting for review in Kochi Developers"
    assert poster.profile.display_name in waiting.body


@pytest.mark.parametrize(
    ("action", "body", "expected", "phrase"),
    [
        ("approve", {}, "SHARE_APPROVED", "Kochi Developers approved “Backend Engineer”"),
        ("reject", {"reason": "Off topic."}, "SHARE_REJECTED", "Reason given: Off topic."),
    ],
)
def test_the_communitys_decision_reaches_the_poster(api_as, shared, action, body, expected, phrase):
    job, community, members, poster, share_id = shared

    api_as(members["MODERATOR"].user).post(
        community_url(community, "submissions", share_id, action), body
    )

    assert told(poster) == [expected]
    rendered = latest(poster)
    assert phrase in f"{rendered.title} {rendered.body}"
    assert rendered.url == f"/opportunities/{job.pk}"


def test_removing_a_shown_opportunity_reaches_whoever_shared_it(api_as):
    community, members = community_with_roles("MEMBER")
    poster = members["MEMBER"].user
    share = distribute(make_job(status="PUBLISHED", creator=poster), community, submitted_by=poster)

    api_as(members["OWNER"].user).post(community_url(community, "submissions", share.pk, "remove"))

    assert told(poster) == ["SHARE_REMOVED"]


def test_a_share_that_needs_no_review_notifies_nobody(api_as):
    community, members = community_with_roles("MEMBER", posting_policy="MEMBERS_AUTO")
    poster = members["MEMBER"].user
    job = make_job(status="PUBLISHED", creator=poster)

    api_as(poster).post(
        f"/api/v1/opportunities/{job.pk}/communities/", {"community_ids": [str(community.pk)]}
    )

    assert not Notification.objects.exists()


def test_a_refused_share_notifies_nobody(api_as):
    """All or nothing applies to the notifications too."""
    community, members = community_with_roles("MEMBER")
    poster = members["MEMBER"].user
    elsewhere, _ = community_with_roles()
    job = make_job(status="PUBLISHED", creator=poster)

    response = api_as(poster).post(
        f"/api/v1/opportunities/{job.pk}/communities/",
        {"community_ids": [str(community.pk), str(elsewhere.pk)]},
    )

    assert response.status_code == 422
    assert not Notification.objects.exists()


# --- Expiry -----------------------------------------------------------------------------


def test_an_expired_opportunity_tells_its_creator_exactly_once():
    job = make_job(
        status="PUBLISHED", title="Backend Engineer", deadline=timezone.now() - timedelta(hours=1)
    )

    opportunity_services.expire_due()
    opportunity_services.expire_due()

    assert told(job.creator) == ["OPPORTUNITY_EXPIRED"]
    notice = Notification.objects.get()
    assert notice.actor is None  # the system did it
    assert render(notice).title == "“Backend Engineer” has expired"
