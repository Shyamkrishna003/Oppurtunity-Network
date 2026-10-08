import io
import uuid
from datetime import date

import pytest
from django.core.files.storage import default_storage
from PIL import Image

from taxonomy.models import Skill
from users.models import (
    PlatformRole,
    ProfileVisibility,
    User,
    UserBlock,
    UserExperience,
    UserProfile,
    UserSkill,
)
from users.services import profiles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

ME = "/api/v1/users/me/"


def set_profile(user, **fields):
    UserProfile.objects.filter(pk=user.pk).update(**fields)


def skill(name):
    return Skill.objects.get(name=name)


# --- Own profile ----------------------------------------------------------------------


def test_me_returns_account_profile_and_skills(api_as):
    user = UserFactory(display_name="Ada Lovelace")
    UserSkill.objects.create(user=user, skill=skill("Python"), kind="HAS")

    body = api_as(user).get(ME).json()

    assert body["email"] == user.email
    assert body["email_verified"] is True
    assert body["platform_role"] == "USER"
    assert body["profile"]["display_name"] == "Ada Lovelace"
    assert body["profile"]["visibility"] == "PUBLIC"
    assert body["profile"]["avatar_url"] is None
    assert [s["name"] for s in body["skills"]["has"]] == ["Python"]
    assert body["skills"]["interested"] == []
    assert "password" not in body


def test_patch_me_updates_profile_fields(api_as):
    user = UserFactory()

    response = api_as(user).patch(
        ME,
        {
            "headline": "Backend engineer",
            "country_code": "in",
            "city": "Kochi",
            "work_mode_preference": "REMOTE",
            "experience_level": "MID",
            "visibility": "PRIVATE",
            "show_contact": True,
        },
    )

    assert response.status_code == 200
    profile = UserProfile.objects.get(pk=user.pk)
    assert (profile.headline, profile.country_code, profile.city) == (
        "Backend engineer",
        "IN",
        "Kochi",
    )
    assert profile.visibility == ProfileVisibility.PRIVATE
    assert profile.show_contact is True
    assert response.json()["profile"]["country_code"] == "IN"


def test_patch_me_cannot_change_account_fields(api_as):
    user = UserFactory()

    response = api_as(user).patch(
        ME, {"email": "other@example.com", "platform_role": "ADMIN", "email_verified": False}
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.platform_role == PlatformRole.USER
    assert user.email != "other@example.com"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("country_code", "IND"),
        ("country_code", "1!"),
        ("visibility", "EVERYONE"),
        ("work_mode_preference", "MOON"),
        ("display_name", ""),
        ("headline", "x" * 141),
        ("bio", "x" * 2001),
    ],
)
def test_patch_me_validates_fields(api_as, field, value):
    response = api_as(UserFactory()).patch(ME, {field: value})

    assert response.status_code == 400
    assert list(response.json()["errors"]) == [field]


# --- Viewing other profiles -----------------------------------------------------------


def view(api_as, viewer, owner):
    return api_as(viewer).get(f"/api/v1/users/{owner.pk}/")


@pytest.mark.parametrize(
    ("visibility", "viewer", "status"),
    [
        ("PUBLIC", "owner", 200),
        ("PUBLIC", "other", 200),
        ("PUBLIC", "moderator", 200),
        ("CONNECTIONS", "owner", 200),
        ("CONNECTIONS", "other", 404),
        ("CONNECTIONS", "moderator", 200),
        ("COMMUNITY", "owner", 200),
        ("COMMUNITY", "other", 404),
        ("COMMUNITY", "moderator", 200),
        ("PRIVATE", "owner", 200),
        ("PRIVATE", "other", 404),
        ("PRIVATE", "moderator", 200),
    ],
)
def test_profile_visibility_matrix(api_as, visibility, viewer, status):
    owner = UserFactory()
    set_profile(owner, visibility=visibility)
    viewers = {
        "owner": owner,
        "other": UserFactory(),
        "moderator": UserFactory(platform_role=PlatformRole.MODERATOR),
    }

    assert view(api_as, viewers[viewer], owner).status_code == status


def test_profiles_require_authentication(api):
    assert api.get(f"/api/v1/users/{UserFactory().pk}/").status_code == 401


def test_hidden_missing_and_deactivated_profiles_look_the_same(api_as):
    viewer = UserFactory()
    hidden = UserFactory()
    set_profile(hidden, visibility="PRIVATE")
    deactivated = UserFactory(is_active=False)

    bodies = []
    for user_id in (hidden.pk, deactivated.pk, uuid.uuid7()):
        response = api_as(viewer).get(f"/api/v1/users/{user_id}/")
        assert response.status_code == 404
        body = response.json()
        body.pop("request_id")
        bodies.append(body)

    assert bodies[0] == bodies[1] == bodies[2]


def test_contact_and_history_sections_follow_their_flags(api_as):
    owner = UserFactory()
    UserExperience.objects.create(
        user=owner, title="Engineer", organization_name="Example Labs", start_date=date(2024, 1, 1)
    )
    viewer = UserFactory()

    set_profile(owner, show_contact=False, show_history=False)
    closed = view(api_as, viewer, owner).json()
    own = view(api_as, owner, owner).json()
    set_profile(owner, show_contact=True, show_history=True)
    opened = view(api_as, viewer, owner).json()

    assert (closed["email"], closed["experiences"], closed["educations"]) == (None, None, None)
    assert own["email"] == owner.email and len(own["experiences"]) == 1
    assert own["is_self"] is True and closed["is_self"] is False
    assert opened["email"] == owner.email
    assert [e["title"] for e in opened["experiences"]] == ["Engineer"]
    assert opened["educations"] == []
    # Settings that are nobody else's business never leave the owner's own endpoint.
    assert not {"visibility", "show_contact", "accepts_referral_requests"} & set(opened)


def test_profile_view_uses_a_fixed_number_of_queries(api_as, django_assert_max_num_queries):
    owner = UserFactory()
    for name in ("Python", "Django", "React"):
        UserSkill.objects.create(user=owner, skill=skill(name), kind="HAS")
    for year in range(2015, 2025):
        UserExperience.objects.create(
            user=owner, title="Role", organization_name="Org", start_date=date(year, 1, 1)
        )
    client = api_as(UserFactory())

    with django_assert_max_num_queries(6):
        assert client.get(f"/api/v1/users/{owner.pk}/").status_code == 200


# --- Blocks ---------------------------------------------------------------------------


def test_a_block_hides_both_profiles_from_each_other(api_as):
    alice, bob, carol = UserFactory(), UserFactory(), UserFactory()

    assert api_as(alice).put(f"/api/v1/users/{bob.pk}/block/").status_code == 204
    assert api_as(alice).put(f"/api/v1/users/{bob.pk}/block/").status_code == 204  # idempotent

    assert UserBlock.objects.filter(blocker=alice, blocked=bob).count() == 1
    assert view(api_as, alice, bob).status_code == 404
    assert view(api_as, bob, alice).status_code == 404
    assert view(api_as, carol, bob).status_code == 200


def test_blocked_users_are_listed_and_can_be_unblocked(api_as):
    alice, bob = UserFactory(), UserFactory(display_name="Bob")
    client = api_as(alice)
    client.put(f"/api/v1/users/{bob.pk}/block/")

    listed = client.get("/api/v1/users/me/blocks/").json()["results"]
    assert [(b["id"], b["display_name"]) for b in listed] == [(str(bob.pk), "Bob")]
    assert api_as(bob).get("/api/v1/users/me/blocks/").json()["results"] == []

    assert client.delete(f"/api/v1/users/{bob.pk}/block/").status_code == 204
    assert view(api_as, bob, alice).status_code == 200


def test_blocking_rules(api_as):
    alice, bob = UserFactory(), UserFactory()

    own = api_as(alice).put(f"/api/v1/users/{alice.pk}/block/")
    missing = api_as(alice).put(f"/api/v1/users/{uuid.uuid7()}/block/")
    # Only the blocker can lift a block.
    api_as(alice).put(f"/api/v1/users/{bob.pk}/block/")
    api_as(bob).delete(f"/api/v1/users/{alice.pk}/block/")

    assert (own.status_code, own.json()["code"]) == (422, "cannot_block_self")
    assert missing.status_code == 204  # does not reveal whether the user exists
    assert UserBlock.objects.filter(blocker=alice, blocked=bob).exists()


# --- Skills ---------------------------------------------------------------------------


def test_put_skills_replaces_both_sets(api_as):
    user = UserFactory()
    python, django, react = skill("Python"), skill("Django"), skill("React")
    UserSkill.objects.create(user=user, skill=react, kind="HAS")
    client = api_as(user)

    response = client.put(
        f"{ME}skills/",
        {"has": [str(python.pk), str(django.pk)], "interested": [str(python.pk), str(react.pk)]},
    )

    assert response.status_code == 200
    body = response.json()
    assert [s["name"] for s in body["has"]] == ["Django", "Python"]
    assert [s["name"] for s in body["interested"]] == ["Python", "React"]
    assert UserSkill.objects.filter(user=user).count() == 4

    assert client.put(f"{ME}skills/", {"has": [], "interested": []}).status_code == 200
    assert not UserSkill.objects.filter(user=user).exists()


def test_put_skills_rejects_unknown_skills_and_oversized_sets(api_as):
    user = UserFactory()
    client = api_as(user)
    known = str(skill("Python").pk)

    unknown = client.put(f"{ME}skills/", {"has": [known, str(uuid.uuid7())], "interested": []})
    too_many = client.put(
        f"{ME}skills/", {"has": [str(uuid.uuid7()) for _ in range(51)], "interested": []}
    )

    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_skill")
    assert too_many.status_code == 400
    assert not UserSkill.objects.filter(user=user).exists()


# --- Experience and education ---------------------------------------------------------


def test_experience_crud_is_scoped_to_the_owner(api_as):
    alice, bob = UserFactory(), UserFactory()
    url = f"{ME}experiences/"
    client = api_as(alice)

    created = client.post(
        url,
        {"title": "Engineer", "organization_name": "Example Labs", "start_date": "2023-01-01"},
    )
    entry_id = created.json()["id"]

    assert created.status_code == 201
    assert [e["id"] for e in client.get(url).json()] == [entry_id]
    assert api_as(bob).get(url).json() == []
    assert api_as(bob).patch(f"{url}{entry_id}/", {"title": "Hacked"}).status_code == 404
    assert api_as(bob).delete(f"{url}{entry_id}/").status_code == 404
    assert client.patch(f"{url}{entry_id}/", {"end_date": "2024-06-30"}).status_code == 200
    assert client.delete(f"{url}{entry_id}/").status_code == 204
    assert not UserExperience.objects.exists()


def test_history_dates_must_be_ordered(api_as):
    client = api_as(UserFactory())
    body = {"institution": "CUSAT", "start_date": "2020-08-01", "end_date": "2019-01-01"}

    created = client.post(f"{ME}educations/", body)
    ok = client.post(f"{ME}educations/", {**body, "end_date": "2024-05-31"})
    patched = client.patch(f"{ME}educations/{ok.json()['id']}/", {"start_date": "2025-01-01"})

    assert (created.status_code, list(created.json()["errors"])) == (400, ["end_date"])
    assert ok.status_code == 201
    assert patched.status_code == 400


def test_history_entries_are_capped(api_as, monkeypatch):
    monkeypatch.setattr(profiles, "MAX_HISTORY_ENTRIES", 1)
    client = api_as(UserFactory())
    body = {"title": "Engineer", "organization_name": "Example Labs", "start_date": "2023-01-01"}

    assert client.post(f"{ME}experiences/", body).status_code == 201
    second = client.post(f"{ME}experiences/", body)

    assert (second.status_code, second.json()["code"]) == (422, "entry_limit_reached")


# --- Avatar ---------------------------------------------------------------------------


def image_file(fmt="PNG", size=(1200, 800), mode="RGB", name="photo.png", **save):
    buffer = io.BytesIO()
    Image.new(mode, size, "navy").save(buffer, fmt, **save)
    buffer.seek(0)
    buffer.name = name
    return buffer


def upload(client, file):
    return client.put(f"{ME}avatar/", {"file": file}, format="multipart")


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_avatar_is_resized_and_reencoded(api_as, fmt):
    user = UserFactory()

    response = upload(api_as(user), image_file(fmt))

    assert response.status_code == 200
    name = UserProfile.objects.get(pk=user.pk).avatar
    assert response.json()["avatar_url"] == f"/media/{name}"
    assert name.startswith("avatars/") and name.endswith(".webp")
    with default_storage.open(name) as stored, Image.open(stored) as image:
        assert image.format == "WEBP"
        assert image.size == (512, 341)


def test_avatar_metadata_and_filename_are_discarded(api_as):
    user = UserFactory()
    exif = Image.Exif()
    exif[0x010E] = "secret location"
    file = image_file("JPEG", name="../../etc/passwd.jpg", exif=exif)

    assert upload(api_as(user), file).status_code == 200

    name = UserProfile.objects.get(pk=user.pk).avatar
    assert "passwd" not in name and ".." not in name
    with default_storage.open(name) as stored, Image.open(stored) as image:
        assert not image.getexif()


def test_replacing_or_removing_the_avatar_deletes_the_old_file(
    api_as, django_capture_on_commit_callbacks
):
    user = UserFactory()
    client = api_as(user)
    upload(client, image_file())
    first = UserProfile.objects.get(pk=user.pk).avatar

    with django_capture_on_commit_callbacks(execute=True):
        upload(client, image_file())
    second = UserProfile.objects.get(pk=user.pk).avatar
    assert first != second
    assert not default_storage.exists(first)

    with django_capture_on_commit_callbacks(execute=True):
        removed = client.delete(f"{ME}avatar/")
    assert removed.json()["avatar_url"] is None
    assert not default_storage.exists(second)


def test_avatar_rejects_files_that_are_not_allowed_images(api_as, settings):
    user = UserFactory()
    client = api_as(user)
    script = io.BytesIO(b"<script>alert(1)</script>")
    script.name = "photo.png"  # extension and client MIME type are not trusted
    gif = image_file("GIF", name="photo.png")
    bomb = image_file("PNG", size=(7000, 7000), mode="1")

    results = [upload(client, f) for f in (script, gif, bomb)]
    missing = client.put(f"{ME}avatar/", {}, format="multipart")
    settings.AVATAR_MAX_BYTES = 100
    too_big = upload(client, image_file())

    assert [(r.status_code, r.json()["code"]) for r in results] == [(422, "invalid_image")] * 3
    assert (missing.status_code, missing.json()["code"]) == (422, "file_required")
    assert (too_big.status_code, too_big.json()["code"]) == (422, "file_too_large")
    assert UserProfile.objects.get(pk=user.pk).avatar == ""


def test_avatar_endpoint_only_accepts_multipart(api_as):
    assert api_as(UserFactory()).put(f"{ME}avatar/", {"file": "x"}).status_code == 415


def test_users_created_outside_registration_have_profiles():
    admin = User.objects.create_superuser("root@example.com", "correct-horse-battery")

    assert admin.profile.display_name == "root"
