import re
import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from audit.models import AuditLog
from organizations.models import Organization, OrganizationInvitation, OrganizationMember
from organizations.tests.factories import MemberFactory, organization_with_roles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

ROLES = ("OWNER", "ADMIN", "RECRUITER", "MEMBER")


def url(organization, *parts) -> str:
    return "/".join([f"/api/v1/organizations/{organization.pk}", *map(str, parts), ""])


def invitation_url(token, action="") -> str:
    return f"/api/v1/organization-invitations/{token}/{action}"


def full_organization():
    return organization_with_roles("ADMIN", "RECRUITER", "MEMBER")


def client_for(api_as, members, who):
    return api_as(UserFactory() if who == "outsider" else members[who].user)


def invite(api_as, organization, actor, email="new@example.com", role="MEMBER"):
    return api_as(actor).post(url(organization, "invitations"), {"email": email, "role": role})


def token_from_last_email():
    return re.search(r"/organization-invitations/(\w+)", mail.outbox[-1].body).group(1)


@pytest.fixture
def invited(api_as, django_capture_on_commit_callbacks):
    """An organization, its owner, and a registered user holding an invitation link."""
    organization, members = organization_with_roles()
    invitee = UserFactory()
    with django_capture_on_commit_callbacks(execute=True):
        invite(api_as, organization, members["OWNER"].user, invitee.email, "RECRUITER")
    return organization, members["OWNER"].user, invitee, token_from_last_email()


# --- Member list ------------------------------------------------------------------------


def test_outsiders_see_only_public_memberships(api, api_as):
    organization, members = organization_with_roles("ADMIN")
    hidden = MemberFactory(organization=organization, is_public=False)
    MemberFactory(organization=organization, status="REMOVED")
    MemberFactory(organization=organization, user=UserFactory(is_active=False))

    as_outsider = api.get(url(organization, "members")).json()["results"]
    as_member = api_as(members["ADMIN"].user).get(url(organization, "members")).json()["results"]

    assert {m["id"] for m in as_outsider} == {str(members["OWNER"].pk), str(members["ADMIN"].pk)}
    assert {m["id"] for m in as_member} == {m["id"] for m in as_outsider} | {str(hidden.pk)}
    assert set(as_outsider[0]["user"]) == {"id", "display_name", "headline", "avatar_url"}


def test_member_list_uses_a_fixed_number_of_queries(api, django_assert_max_num_queries):
    organization, _ = organization_with_roles()
    for _ in range(10):
        MemberFactory(organization=organization)

    with django_assert_max_num_queries(3):
        assert len(api.get(url(organization, "members")).json()["results"]) == 11


# --- Inviting ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "role", "status"),
    [
        *[("OWNER", role, 201) for role in ROLES],
        ("ADMIN", "RECRUITER", 201),
        ("ADMIN", "MEMBER", 201),
        ("ADMIN", "ADMIN", 403),
        ("ADMIN", "OWNER", 403),
        *[(who, "MEMBER", 403) for who in ("RECRUITER", "MEMBER", "outsider")],
    ],
)
def test_who_may_invite_whom(api_as, who, role, status):
    organization, members = full_organization()

    response = client_for(api_as, members, who).post(
        url(organization, "invitations"), {"email": "new@example.com", "role": role}
    )

    assert response.status_code == status
    assert OrganizationInvitation.objects.count() == (1 if status == 201 else 0)


def test_inviting_emails_a_link_and_stores_only_a_hash(api_as, django_capture_on_commit_callbacks):
    organization, members = organization_with_roles()

    with django_capture_on_commit_callbacks(execute=True):
        response = invite(api_as, organization, members["OWNER"].user, " New@Example.com ")

    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"
    assert "token" not in str(response.json())
    (message,) = mail.outbox
    assert message.to == ["new@example.com"]
    assert organization.name in message.subject
    token = token_from_last_email()
    assert f"http://app.test/organization-invitations/{token}" in message.body
    invitation = OrganizationInvitation.objects.get()
    assert token not in str(invitation.__dict__)
    assert invitation.expires_at > timezone.now() + timedelta(days=6)
    log = AuditLog.objects.get(action="organization.member_invited")
    assert (log.metadata, log.organization_id) == ({"role": "MEMBER"}, organization.pk)
    assert "new@example.com" not in str(log.metadata)


def test_invitation_conflicts(api_as):
    organization, members = organization_with_roles("MEMBER")
    owner = members["OWNER"].user

    assert invite(api_as, organization, owner).status_code == 201
    duplicate = invite(api_as, organization, owner, "NEW@example.com")
    member = invite(api_as, organization, owner, members["MEMBER"].user.email)

    assert (duplicate.status_code, duplicate.json()["code"]) == (409, "invitation_pending")
    assert (member.status_code, member.json()["code"]) == (409, "already_member")


def test_an_expired_invitation_does_not_block_a_new_one(api_as):
    organization, members = organization_with_roles()
    owner = members["OWNER"].user
    invite(api_as, organization, owner)
    OrganizationInvitation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

    assert invite(api_as, organization, owner).status_code == 201
    statuses = OrganizationInvitation.objects.order_by("created_at").values_list(
        "status", flat=True
    )
    assert list(statuses) == ["EXPIRED", "PENDING"]


def test_cannot_invite_into_a_suspended_organization(api_as):
    organization, members = organization_with_roles()
    Organization.objects.filter(pk=organization.pk).update(status="SUSPENDED")

    response = invite(api_as, organization, members["OWNER"].user)

    assert (response.status_code, response.json()["code"]) == (422, "organization_suspended")


@pytest.mark.parametrize(
    ("who", "status"),
    [("OWNER", 200), ("ADMIN", 200), ("RECRUITER", 403), ("MEMBER", 403), ("outsider", 403)],
)
def test_only_managers_see_open_invitations(api_as, who, status):
    organization, members = full_organization()
    invite(api_as, organization, members["OWNER"].user)
    invite(api_as, organization, members["OWNER"].user, "old@example.com")
    OrganizationInvitation.objects.filter(email="old@example.com").update(status="REVOKED")

    response = client_for(api_as, members, who).get(url(organization, "invitations"))

    assert response.status_code == status
    if status == 200:
        assert [i["email"] for i in response.json()["results"]] == ["new@example.com"]


def test_revoking_follows_the_same_limits_as_inviting(api_as):
    organization, members = organization_with_roles("ADMIN")
    owner, admin = members["OWNER"].user, members["ADMIN"].user
    for_admin = invite(api_as, organization, owner, "a@example.com", "ADMIN").json()["id"]
    for_member = invite(api_as, organization, owner, "m@example.com", "MEMBER").json()["id"]

    assert api_as(admin).delete(url(organization, "invitations", for_admin)).status_code == 403
    assert api_as(admin).delete(url(organization, "invitations", for_member)).status_code == 204
    again = api_as(owner).delete(url(organization, "invitations", for_member))
    assert (again.status_code, again.json()["code"]) == (409, "invitation_closed")
    assert api_as(owner).delete(url(organization, "invitations", for_admin)).status_code == 204
    assert api_as(owner).delete(url(organization, "invitations", uuid.uuid7())).status_code == 404


# --- Responding to an invitation --------------------------------------------------------


def test_the_invited_person_can_view_and_accept_once(api_as, invited):
    organization, owner, invitee, token = invited
    client = api_as(invitee)

    preview = client.get(invitation_url(token))
    accepted = client.post(invitation_url(token, "accept/"))
    again = client.post(invitation_url(token, "accept/"))

    assert preview.status_code == 200
    assert preview.json()["organization"]["name"] == organization.name
    assert (preview.json()["role"], preview.json()["status"]) == ("RECRUITER", "PENDING")
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "RECRUITER"
    assert (again.status_code, again.json()["code"]) == (409, "invitation_closed")
    membership = OrganizationMember.objects.get(organization=organization, user=invitee)
    assert (membership.role, membership.status) == ("RECRUITER", "ACTIVE")
    log = AuditLog.objects.get(action="organization.member_joined")
    assert (log.actor, log.target_id) == (invitee, membership.pk)


def test_an_invitation_cannot_be_used_by_another_account(api_as, invited):
    organization, _, _, token = invited
    other = api_as(UserFactory())

    for response in (
        other.get(invitation_url(token)),
        other.post(invitation_url(token, "accept/")),
        other.post(invitation_url(token, "decline/")),
    ):
        assert (response.status_code, response.json()["code"]) == (403, "invitation_email_mismatch")
        assert organization.name not in response.content.decode()
    assert OrganizationInvitation.objects.get().status == "PENDING"
    assert OrganizationMember.objects.filter(organization=organization).count() == 1


def test_accepting_requires_a_verified_email(api_as, django_capture_on_commit_callbacks):
    organization, members = organization_with_roles()
    invitee = UserFactory(unverified=True)
    with django_capture_on_commit_callbacks(execute=True):
        invite(api_as, organization, members["OWNER"].user, invitee.email)

    response = api_as(invitee).post(invitation_url(token_from_last_email(), "accept/"))

    assert (response.status_code, response.json()["code"]) == (403, "email_not_verified")
    assert not OrganizationMember.objects.filter(user=invitee).exists()


def test_an_unconfirmed_account_claiming_the_invited_address_can_do_nothing_with_the_link(
    api_as, django_capture_on_commit_callbacks
):
    """Anyone can register an address they do not own. Until it is confirmed, that account
    must not be able to see, decline or accept an invitation sent to the address."""
    organization, members = organization_with_roles()
    squatter = UserFactory(unverified=True)
    with django_capture_on_commit_callbacks(execute=True):
        invite(api_as, organization, members["OWNER"].user, squatter.email)
    token = token_from_last_email()
    client = api_as(squatter)

    responses = [
        client.get(invitation_url(token)),
        client.post(invitation_url(token, "decline/")),
        client.post(invitation_url(token, "accept/")),
        client.get(invitation_url("0" * 64)),  # a made-up link gets the same answer
    ]

    for response in responses:
        assert (response.status_code, response.json()["code"]) == (403, "email_not_verified")
        assert organization.name not in response.content.decode()
    assert OrganizationInvitation.objects.get().status == "PENDING"
    assert not OrganizationMember.objects.filter(user=squatter).exists()


def test_invitation_links_require_sign_in_and_a_real_token(api, api_as, invited):
    _, _, invitee, token = invited

    assert api.get(invitation_url(token)).status_code == 401
    assert api.post(invitation_url(token, "accept/")).status_code == 401
    assert api_as(invitee).get(invitation_url("0" * 64)).status_code == 404
    assert api_as(invitee).post(invitation_url(token[:-1] + "x", "accept/")).status_code == 404


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"expires_at": timezone.now() - timedelta(minutes=1)}, "invitation_expired"),
        ({"status": "REVOKED"}, "invitation_closed"),
    ],
)
def test_expired_and_revoked_invitations_cannot_be_accepted(api_as, invited, change, code):
    _, _, invitee, token = invited
    OrganizationInvitation.objects.update(**change)

    response = api_as(invitee).post(invitation_url(token, "accept/"))

    assert (response.status_code, response.json()["code"]) == (409, code)
    assert not OrganizationMember.objects.filter(user=invitee).exists()
    expected = "EXPIRED" if code == "invitation_expired" else "REVOKED"
    assert api_as(invitee).get(invitation_url(token)).json()["status"] == expected


def test_declining_closes_the_invitation(api_as, invited):
    _, _, invitee, token = invited
    client = api_as(invitee)

    assert client.post(invitation_url(token, "decline/")).status_code == 204
    assert client.post(invitation_url(token, "accept/")).status_code == 409
    assert OrganizationInvitation.objects.get().status == "DECLINED"
    assert not OrganizationMember.objects.filter(user=invitee).exists()
    assert AuditLog.objects.filter(action="organization.invitation_declined").exists()


def test_a_former_member_rejoins_through_a_new_invitation(
    api_as, django_capture_on_commit_callbacks
):
    organization, members = organization_with_roles()
    former = MemberFactory(organization=organization, role="ADMIN", status="LEFT")
    with django_capture_on_commit_callbacks(execute=True):
        invite(api_as, organization, members["OWNER"].user, former.user.email, "MEMBER")

    api_as(former.user).post(invitation_url(token_from_last_email(), "accept/"))

    former.refresh_from_db()
    assert (former.status, former.role) == ("ACTIVE", "MEMBER")  # the old role does not return
    assert OrganizationMember.objects.filter(user=former.user).count() == 1


# --- Changing roles ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "target", "new_role", "status"),
    [
        *[("OWNER", target, role, 200) for target in ("ADMIN", "MEMBER") for role in ROLES],
        ("ADMIN", "RECRUITER", "MEMBER", 200),
        ("ADMIN", "MEMBER", "RECRUITER", 200),
        ("ADMIN", "MEMBER", "ADMIN", 403),
        ("ADMIN", "MEMBER", "OWNER", 403),
        ("ADMIN", "OWNER", "MEMBER", 403),
        ("RECRUITER", "MEMBER", "RECRUITER", 403),
        ("MEMBER", "RECRUITER", "MEMBER", 403),
        ("outsider", "MEMBER", "RECRUITER", 403),
        # Nobody changes their own role.
        ("OWNER", "OWNER", "ADMIN", 403),
        ("ADMIN", "ADMIN", "OWNER", 403),
        ("MEMBER", "MEMBER", "OWNER", 403),
    ],
)
def test_who_may_change_which_role(api_as, who, target, new_role, status):
    organization, members = full_organization()
    before = members[target].role

    response = client_for(api_as, members, who).patch(
        url(organization, "members", members[target].pk), {"role": new_role}
    )

    assert response.status_code == status
    members[target].refresh_from_db()
    assert members[target].role == (new_role if status == 200 else before)


def test_an_admin_cannot_change_another_admin(api_as):
    organization, members = organization_with_roles("ADMIN")
    other_admin = MemberFactory(organization=organization, role="ADMIN")

    response = api_as(members["ADMIN"].user).patch(
        url(organization, "members", other_admin.pk), {"role": "MEMBER"}
    )

    assert response.status_code == 403


def test_role_changes_are_audited(api_as):
    organization, members = organization_with_roles("MEMBER")

    api_as(members["OWNER"].user).patch(
        url(organization, "members", members["MEMBER"].pk), {"role": "RECRUITER"}
    )

    log = AuditLog.objects.get(action="organization.role_changed")
    assert log.metadata == {"from": "MEMBER", "to": "RECRUITER"}
    assert (log.actor, log.target_id) == (members["OWNER"].user, members["MEMBER"].pk)


def test_member_update_accepts_exactly_one_known_field(api_as):
    organization, members = organization_with_roles("MEMBER")
    client = api_as(members["OWNER"].user)
    target = url(organization, "members", members["MEMBER"].pk)

    assert client.patch(target, {}).status_code == 400
    assert client.patch(target, {"role": "ADMIN", "is_public": False}).status_code == 400
    assert client.patch(target, {"role": "SUPERUSER"}).status_code == 400
    assert client.patch(target, {"status": "REMOVED"}).status_code == 400


def test_members_of_one_organization_cannot_be_reached_through_another(api_as):
    mine, my_members = organization_with_roles()
    _, their_members = organization_with_roles("MEMBER")
    client = api_as(my_members["OWNER"].user)
    foreign = their_members["MEMBER"]

    assert client.patch(url(mine, "members", foreign.pk), {"role": "ADMIN"}).status_code == 404
    assert client.delete(url(mine, "members", foreign.pk)).status_code == 404
    assert (
        client.post(url(mine, "transfer-ownership"), {"member_id": str(foreign.pk)}).status_code
        == 404
    )
    foreign.refresh_from_db()
    assert (foreign.role, foreign.status) == ("MEMBER", "ACTIVE")


# --- Removing and leaving ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "target", "status"),
    [
        ("OWNER", "ADMIN", 204),
        ("OWNER", "MEMBER", 204),
        ("ADMIN", "RECRUITER", 204),
        ("ADMIN", "MEMBER", 204),
        ("ADMIN", "OWNER", 403),
        ("RECRUITER", "MEMBER", 403),
        ("MEMBER", "RECRUITER", 403),
        ("outsider", "MEMBER", 403),
        ("OWNER", "OWNER", 403),  # removing yourself is "leave"
        ("ADMIN", "ADMIN", 403),
    ],
)
def test_who_may_remove_whom(api_as, who, target, status):
    organization, members = full_organization()

    response = client_for(api_as, members, who).delete(
        url(organization, "members", members[target].pk)
    )

    assert response.status_code == status
    members[target].refresh_from_db()
    assert members[target].status == ("REMOVED" if status == 204 else "ACTIVE")


def test_a_removed_member_loses_access_immediately(api_as):
    organization, members = organization_with_roles("ADMIN")
    admin = api_as(members["ADMIN"].user)
    assert admin.patch(url(organization), {"city": "Kochi"}).status_code == 200

    api_as(members["OWNER"].user).delete(url(organization, "members", members["ADMIN"].pk))

    assert admin.patch(url(organization), {"city": "Elsewhere"}).status_code == 403
    assert admin.get(url(organization, "invitations")).status_code == 403
    assert AuditLog.objects.get(action="organization.member_removed").metadata == {"role": "ADMIN"}


def test_leaving(api_as):
    organization, members = organization_with_roles("MEMBER")
    member, owner = members["MEMBER"], members["OWNER"]

    assert api_as(member.user).post(url(organization, "leave")).status_code == 204
    assert api_as(member.user).post(url(organization, "leave")).status_code == 404
    assert api_as(UserFactory()).post(url(organization, "leave")).status_code == 404
    member.refresh_from_db()
    assert member.status == "LEFT"

    last = api_as(owner.user).post(url(organization, "leave"))
    assert (last.status_code, last.json()["code"]) == (409, "last_owner")
    owner.refresh_from_db()
    assert owner.status == "ACTIVE"


def test_an_owner_may_leave_when_another_owner_remains(api_as):
    organization, members = organization_with_roles()
    MemberFactory(organization=organization, role="OWNER")

    assert api_as(members["OWNER"].user).post(url(organization, "leave")).status_code == 204


# --- Ownership and visibility -----------------------------------------------------------


def test_transferring_ownership_swaps_the_two_roles(api_as):
    organization, members = organization_with_roles("MEMBER")
    owner, member = members["OWNER"], members["MEMBER"]

    response = api_as(owner.user).post(
        url(organization, "transfer-ownership"), {"member_id": str(member.pk)}
    )

    assert response.status_code == 200
    assert response.json()["viewer"]["role"] == "ADMIN"
    owner.refresh_from_db()
    member.refresh_from_db()
    assert (owner.role, member.role) == ("ADMIN", "OWNER")
    assert AuditLog.objects.filter(action="organization.ownership_transferred").count() == 1


def test_transfer_rules(api_as):
    organization, members = organization_with_roles("ADMIN", "MEMBER")
    target = {"member_id": str(members["MEMBER"].pk)}
    transfer = url(organization, "transfer-ownership")

    by_admin = api_as(members["ADMIN"].user).post(transfer, target)
    to_self = api_as(members["OWNER"].user).post(transfer, {"member_id": str(members["OWNER"].pk)})
    to_former = api_as(members["OWNER"].user).post(
        transfer,
        {"member_id": str(MemberFactory(organization=organization, status="LEFT").pk)},
    )

    assert by_admin.status_code == 403
    assert (to_self.status_code, to_self.json()["code"]) == (422, "already_owner")
    assert to_former.status_code == 404
    members["OWNER"].refresh_from_db()
    assert members["OWNER"].role == "OWNER"


def test_only_the_member_decides_whether_their_membership_is_public(api, api_as):
    organization, members = organization_with_roles("MEMBER")
    member = members["MEMBER"]
    target = url(organization, "members", member.pk)

    by_owner = api_as(members["OWNER"].user).patch(target, {"is_public": False})
    by_self = api_as(member.user).patch(target, {"is_public": False})

    assert by_owner.status_code == 403
    assert (by_self.status_code, by_self.json()["is_public"]) == (200, False)
    listed = api.get(url(organization, "members")).json()["results"]
    assert str(member.pk) not in {m["id"] for m in listed}
