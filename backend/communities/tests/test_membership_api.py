import uuid

import pytest
from django.core import mail

from audit.models import AuditLog
from communities.models import Community, CommunityMember
from communities.tests.factories import (
    CommunityFactory,
    CommunityMemberFactory,
    community_with_roles,
)
from users.models import UserBlock, UserProfile
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

ROLES = ("OWNER", "ADMIN", "MODERATOR", "MEMBER")


def url(community, *parts) -> str:
    return "/".join([f"/api/v1/communities/{community.pk}", *map(str, parts), ""])


def full_community(**fields):
    return community_with_roles("ADMIN", "MODERATOR", "MEMBER", **fields)


def client_for(api_as, members, who):
    return api_as(UserFactory() if who == "outsider" else members[who].user)


def status_of(community, user):
    row = CommunityMember.objects.filter(community=community, user=user).first()
    return row.status if row else None


def changes():
    return [
        (log.metadata["from"], log.metadata["to"])
        for log in AuditLog.objects.filter(action="community.membership_changed").order_by(
            "created_at"
        )
    ]


# --- Joining ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("join_policy", "status", "member_count"),
    [("OPEN", "ACTIVE", 2), ("APPROVAL", "PENDING", 1)],
)
def test_joining_follows_the_join_policy_and_is_repeatable(
    api_as, join_policy, status, member_count
):
    community, _ = community_with_roles(join_policy=join_policy)
    user = UserFactory()
    client = api_as(user)

    first = client.post(url(community, "join"))
    second = client.post(url(community, "join"))

    assert first.status_code == second.status_code == 200
    assert first.json()["viewer"]["status"] == status
    assert first.json()["member_count"] == member_count
    assert CommunityMember.objects.filter(community=community, user=user).count() == 1
    assert changes() == [(None, status)]


def test_an_invite_only_community_cannot_be_joined_without_an_invitation(api_as):
    community, _ = community_with_roles(join_policy="INVITE_ONLY")
    user = UserFactory()

    response = api_as(user).post(url(community, "join"))

    assert (response.status_code, response.json()["code"]) == (422, "invitation_required")
    assert status_of(community, user) is None


def test_joining_requires_a_verified_account(api, api_as):
    community = CommunityFactory()
    unverified = UserFactory(unverified=True)

    assert api.post(url(community, "join")).status_code == 401
    response = api_as(unverified).post(url(community, "join"))
    assert (response.status_code, response.json()["code"]) == (403, "email_not_verified")
    assert status_of(community, unverified) is None


@pytest.mark.parametrize("change", [{"visibility": "PRIVATE"}, {"status": "SUSPENDED"}])
def test_hidden_communities_cannot_be_joined(api_as, change):
    community = CommunityFactory(**change)
    user = UserFactory()

    assert api_as(user).post(url(community, "join")).status_code == 404
    assert status_of(community, user) is None


def test_a_banned_person_cannot_rejoin_until_the_ban_is_lifted(api_as):
    community, members = community_with_roles()
    banned = CommunityMemberFactory(community=community, status="BANNED")
    client = api_as(banned.user)

    refused = client.post(url(community, "join"))
    assert (refused.status_code, refused.json()["code"]) == (409, "banned")
    assert client.post(url(community, "leave")).status_code == 404

    unbanned = api_as(members["OWNER"].user).post(url(community, "members", banned.pk, "unban"))
    assert (unbanned.status_code, unbanned.json()["status"]) == (200, "REMOVED")
    assert client.post(url(community, "join")).json()["viewer"]["status"] == "ACTIVE"


def test_a_returning_member_comes_back_as_an_ordinary_member(api_as):
    community, members = community_with_roles("ADMIN")
    admin = members["ADMIN"]
    client = api_as(admin.user)

    assert client.post(url(community, "leave")).status_code == 204
    admin.refresh_from_db()
    assert (admin.status, admin.role) == ("LEFT", "MEMBER")

    viewer = client.post(url(community, "join")).json()["viewer"]
    assert (viewer["status"], viewer["role"], viewer["can_manage"]) == ("ACTIVE", "MEMBER", False)
    assert CommunityMember.objects.filter(user=admin.user).count() == 1
    assert changes() == [("ACTIVE", "LEFT"), ("LEFT", "ACTIVE")]


# --- Leaving ----------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["ACTIVE", "INVITED", "PENDING"])
def test_leaving_also_declines_an_invitation_and_withdraws_a_request(api_as, status):
    community, _ = community_with_roles()
    member = CommunityMemberFactory(community=community, status=status)
    client = api_as(member.user)

    assert client.post(url(community, "leave")).status_code == 204
    assert client.post(url(community, "leave")).status_code == 404
    assert status_of(community, member.user) == "LEFT"


def test_the_last_owner_cannot_leave(api_as):
    community, members = community_with_roles("ADMIN")
    owner = members["OWNER"]

    last = api_as(owner.user).post(url(community, "leave"))
    assert (last.status_code, last.json()["code"]) == (409, "last_owner")

    CommunityMemberFactory(community=community, role="OWNER")
    assert api_as(owner.user).post(url(community, "leave")).status_code == 204


def test_leaving_a_community_you_are_not_in_is_not_found(api_as):
    assert api_as(UserFactory()).post(url(CommunityFactory(), "leave")).status_code == 404


# --- Requests to join -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "approve", "reject"),
    [
        ("OWNER", 200, 200),
        ("ADMIN", 200, 200),
        ("MODERATOR", 200, 403),
        ("MEMBER", 403, 403),
        ("outsider", 403, 403),
    ],
)
def test_who_may_approve_and_reject_requests(api_as, who, approve, reject):
    community, members = full_community(join_policy="APPROVAL")
    first = CommunityMemberFactory(community=community, status="PENDING")
    second = CommunityMemberFactory(community=community, status="PENDING")
    client = client_for(api_as, members, who)

    approved = client.post(url(community, "members", first.pk, "approve"))
    rejected = client.post(url(community, "members", second.pk, "reject"))

    assert (approved.status_code, rejected.status_code) == (approve, reject)
    assert status_of(community, first.user) == ("ACTIVE" if approve == 200 else "PENDING")
    assert status_of(community, second.user) == ("REJECTED" if reject == 200 else "PENDING")


def test_approval_is_repeatable_and_applies_only_to_requests(api_as):
    community, members = community_with_roles("MEMBER", join_policy="APPROVAL")
    pending = CommunityMemberFactory(community=community, status="PENDING")
    client = api_as(members["OWNER"].user)

    assert client.post(url(community, "members", pending.pk, "approve")).status_code == 200
    assert client.post(url(community, "members", pending.pk, "approve")).status_code == 200
    late = client.post(url(community, "members", pending.pk, "reject"))
    not_a_request = client.post(url(community, "members", members["MEMBER"].pk, "unban"))

    assert (late.status_code, late.json()["code"]) == (409, "invalid_transition")
    assert not_a_request.status_code == 409
    assert changes() == [("PENDING", "ACTIVE")]
    pending.refresh_from_db()
    assert pending.joined_at is not None


def test_a_person_cannot_approve_their_own_request(api_as):
    community, _ = community_with_roles(join_policy="APPROVAL")
    pending = CommunityMemberFactory(community=community, status="PENDING")

    response = api_as(pending.user).post(url(community, "members", pending.pk, "approve"))

    assert response.status_code == 403
    assert status_of(community, pending.user) == "PENDING"


# --- Removing and banning ---------------------------------------------------------------


@pytest.mark.parametrize("action", ["remove", "ban"])
@pytest.mark.parametrize(
    ("who", "target", "status"),
    [
        ("OWNER", "ADMIN", 200),
        ("OWNER", "MEMBER", 200),
        ("ADMIN", "MODERATOR", 200),
        ("ADMIN", "MEMBER", 200),
        ("ADMIN", "OWNER", 403),
        ("MODERATOR", "MEMBER", 403),
        ("MEMBER", "MODERATOR", 403),
        ("outsider", "MEMBER", 403),
        ("OWNER", "OWNER", 403),
        ("ADMIN", "ADMIN", 403),
    ],
)
def test_who_may_remove_and_ban_whom(api_as, action, who, target, status):
    community, members = full_community()

    response = client_for(api_as, members, who).post(
        url(community, "members", members[target].pk, action)
    )

    assert response.status_code == status
    after = {"remove": "REMOVED", "ban": "BANNED"}[action] if status == 200 else "ACTIVE"
    members[target].refresh_from_db()
    assert members[target].status == after
    if status == 200:
        assert members[target].role == "MEMBER"  # the role does not survive removal


def test_an_admin_cannot_act_on_another_admin(api_as):
    community, members = community_with_roles("ADMIN")
    other = CommunityMemberFactory(community=community, role="ADMIN")
    client = api_as(members["ADMIN"].user)

    assert client.post(url(community, "members", other.pk, "remove")).status_code == 403
    assert client.post(url(community, "members", other.pk, "ban")).status_code == 403
    assert client.patch(url(community, "members", other.pk), {"role": "MEMBER"}).status_code == 403


def test_a_removed_admin_loses_access_immediately(api_as):
    community, members = community_with_roles("ADMIN")
    admin = api_as(members["ADMIN"].user)
    assert admin.patch(url(community), {"category": "Tech"}).status_code == 200

    api_as(members["OWNER"].user).post(url(community, "members", members["ADMIN"].pk, "remove"))

    assert admin.patch(url(community), {"category": "Other"}).status_code == 403
    assert admin.get(url(community, "members")).status_code == 403


def test_members_of_one_community_cannot_be_reached_through_another(api_as):
    mine, my_members = community_with_roles()
    _, their_members = community_with_roles("MEMBER")
    client = api_as(my_members["OWNER"].user)
    foreign = their_members["MEMBER"]

    for action in ("approve", "reject", "remove", "ban", "unban"):
        assert client.post(url(mine, "members", foreign.pk, action)).status_code == 404
    assert client.patch(url(mine, "members", foreign.pk), {"role": "ADMIN"}).status_code == 404
    assert client.post(url(mine, "members", foreign.pk, "promote")).status_code == 404
    foreign.refresh_from_db()
    assert (foreign.role, foreign.status) == ("MEMBER", "ACTIVE")


# --- Roles ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "target", "new_role", "status"),
    [
        *[("OWNER", "MEMBER", role, 200) for role in ROLES],
        ("OWNER", "ADMIN", "MODERATOR", 200),
        ("ADMIN", "MEMBER", "MODERATOR", 200),
        ("ADMIN", "MODERATOR", "MEMBER", 200),
        ("ADMIN", "MEMBER", "ADMIN", 403),
        ("ADMIN", "OWNER", "MEMBER", 403),
        ("MODERATOR", "MEMBER", "MODERATOR", 403),
        ("outsider", "MEMBER", "MODERATOR", 403),
        ("OWNER", "OWNER", "ADMIN", 403),
        ("MEMBER", "MEMBER", "OWNER", 403),
    ],
)
def test_who_may_change_which_role(api_as, who, target, new_role, status):
    community, members = full_community()
    before = members[target].role

    response = client_for(api_as, members, who).patch(
        url(community, "members", members[target].pk), {"role": new_role}
    )

    assert response.status_code == status
    members[target].refresh_from_db()
    assert members[target].role == (new_role if status == 200 else before)


def test_role_changes_are_audited_and_need_an_active_member(api_as):
    community, members = community_with_roles("MEMBER")
    invited = CommunityMemberFactory(community=community, status="INVITED")
    client = api_as(members["OWNER"].user)

    client.patch(url(community, "members", members["MEMBER"].pk), {"role": "MODERATOR"})
    on_invitee = client.patch(url(community, "members", invited.pk), {"role": "ADMIN"})

    log = AuditLog.objects.get(action="community.role_changed")
    assert log.metadata == {"from": "MEMBER", "to": "MODERATOR"}
    assert log.community_id == community.pk
    assert on_invitee.status_code == 403
    unknown_role = client.patch(url(community, "members", members["MEMBER"].pk), {"role": "KING"})
    assert unknown_role.status_code == 400


# --- Invitations ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "status"),
    [("OWNER", 201), ("ADMIN", 201), ("MODERATOR", 403), ("MEMBER", 403), ("outsider", 403)],
)
def test_only_owners_and_admins_can_invite(api_as, who, status):
    community, members = full_community()
    invitee = UserFactory()

    response = client_for(api_as, members, who).post(
        url(community, "invitations"), {"user_id": str(invitee.pk)}
    )

    assert response.status_code == status
    assert status_of(community, invitee) == ("INVITED" if status == 201 else None)


def test_an_invitation_emails_the_person_and_opens_a_private_community(
    api_as, django_capture_on_commit_callbacks
):
    community, members = community_with_roles(visibility="PRIVATE", join_policy="INVITE_ONLY")
    invitee = UserFactory()
    client = api_as(invitee)
    assert client.get(url(community)).status_code == 404

    with django_capture_on_commit_callbacks(execute=True):
        api_as(members["OWNER"].user).post(
            url(community, "invitations"), {"user_id": str(invitee.pk)}
        )

    (message,) = mail.outbox
    assert message.to == [invitee.email]
    assert f"http://app.test/communities/{community.pk}" in message.body
    viewer = client.get(url(community)).json()["viewer"]
    assert (viewer["status"], viewer["join_action"]) == ("INVITED", "accept")
    assert client.get(url(community, "members")).status_code == 403  # not a member yet

    accepted = client.post(url(community, "join")).json()["viewer"]
    assert (accepted["status"], accepted["role"]) == ("ACTIVE", "MEMBER")
    assert changes() == [(None, "INVITED"), ("INVITED", "ACTIVE")]


@pytest.mark.parametrize(
    ("existing", "status", "code"),
    [
        ("INVITED", 201, None),  # repeating an invitation changes nothing
        ("LEFT", 201, None),
        ("REMOVED", 201, None),
        ("ACTIVE", 409, "already_member"),
        ("PENDING", 409, "request_pending"),
        ("BANNED", 409, "banned"),
    ],
)
def test_inviting_someone_who_already_has_a_membership_row(api_as, existing, status, code):
    community, members = community_with_roles()
    row = CommunityMemberFactory(community=community, status=existing)

    response = api_as(members["OWNER"].user).post(
        url(community, "invitations"), {"user_id": str(row.user_id)}
    )

    assert response.status_code == status
    if code:
        assert response.json()["code"] == code
        assert status_of(community, row.user) == existing
    else:
        assert status_of(community, row.user) == "INVITED"


def test_only_people_whose_profile_the_inviter_can_open_can_be_invited(api_as):
    community, members = community_with_roles()
    owner = members["OWNER"].user
    client = api_as(owner)
    private, blocker = UserFactory(), UserFactory()
    UserProfile.objects.filter(pk=private.pk).update(visibility="PRIVATE")
    UserBlock.objects.create(blocker=blocker, blocked=owner)

    responses = [
        client.post(url(community, "invitations"), {"user_id": str(user_id)})
        for user_id in (private.pk, blocker.pk, uuid.uuid7())
    ]
    own = client.post(url(community, "invitations"), {"user_id": str(owner.pk)})

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert (own.status_code, own.json()["code"]) == (422, "cannot_invite_self")
    assert CommunityMember.objects.filter(community=community).count() == 1


def test_an_unanswered_invitation_can_be_withdrawn(api_as):
    community, members = community_with_roles(visibility="PRIVATE")
    invited = CommunityMemberFactory(community=community, status="INVITED")

    response = api_as(members["OWNER"].user).post(url(community, "members", invited.pk, "remove"))

    assert response.status_code == 200
    assert api_as(invited.user).get(url(community)).status_code == 404


# --- Member lists -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "active", "pending", "invited", "banned"),
    [
        ("OWNER", 200, 200, 200, 200),
        ("ADMIN", 200, 200, 200, 200),
        ("MODERATOR", 200, 200, 403, 403),
        ("MEMBER", 200, 403, 403, 403),
        ("outsider", 403, 403, 403, 403),
    ],
)
def test_who_may_list_people_in_each_state(api_as, who, active, pending, invited, banned):
    community, members = full_community()
    for status in ("PENDING", "INVITED", "BANNED"):
        CommunityMemberFactory(community=community, status=status)
    client = client_for(api_as, members, who)

    def listing(status):
        return client.get(url(community, "members"), {"status": status})

    results = {status: listing(status) for status in ("ACTIVE", "PENDING", "INVITED", "BANNED")}

    assert [r.status_code for r in results.values()] == [active, pending, invited, banned]
    if active == 200:
        assert len(results["ACTIVE"].json()["results"]) == 4
        assert client.get(url(community, "members")).json() == results["ACTIVE"].json()
    if pending == 200:
        assert [m["status"] for m in results["PENDING"].json()["results"]] == ["PENDING"]


def test_member_list_rejects_states_that_are_not_listable(api, api_as):
    community, members = community_with_roles()

    response = api_as(members["OWNER"].user).get(url(community, "members"), {"status": "LEFT"})

    assert (response.status_code, list(response.json()["errors"])) == (400, ["status"])
    assert api.get(url(community, "members")).status_code == 401


def test_member_list_uses_a_fixed_number_of_queries(api_as, django_assert_max_num_queries):
    community, members = community_with_roles()
    for _ in range(10):
        CommunityMemberFactory(community=community)
    client = api_as(members["OWNER"].user)

    with django_assert_max_num_queries(5):
        assert len(client.get(url(community, "members")).json()["results"]) == 11


# --- Suspension and profile visibility --------------------------------------------------


def test_a_suspended_community_freezes_membership_except_leaving(api_as):
    community, members = community_with_roles("MEMBER")
    pending = CommunityMemberFactory(community=community, status="PENDING")
    Community.objects.filter(pk=community.pk).update(status="SUSPENDED")
    owner = api_as(members["OWNER"].user)

    approve = owner.post(url(community, "members", pending.pk, "approve"))
    invite = owner.post(url(community, "invitations"), {"user_id": str(UserFactory().pk)})

    assert approve.json()["code"] == invite.json()["code"] == "community_suspended"
    assert api_as(members["MEMBER"].user).post(url(community, "leave")).status_code == 204


def test_community_members_profile_visibility_follows_shared_membership(api_as):
    community, members = community_with_roles("MEMBER")
    owner_of_profile = members["MEMBER"].user
    UserProfile.objects.filter(pk=owner_of_profile.pk).update(visibility="COMMUNITY")
    fellow = members["OWNER"].user
    pending = CommunityMemberFactory(community=community, status="PENDING").user
    stranger = CommunityMemberFactory().user  # active, but in a different community
    profile = f"/api/v1/users/{owner_of_profile.pk}/"

    assert api_as(fellow).get(profile).status_code == 200
    assert api_as(pending).get(profile).status_code == 404
    assert api_as(stranger).get(profile).status_code == 404

    api_as(fellow).post(url(community, "members", members["MEMBER"].pk, "remove"))
    assert api_as(fellow).get(profile).status_code == 404
