import re
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings as django_settings
from django.core import mail
from django.utils import timezone

from audit.models import AuditLog
from common.throttles import ScopedThrottle
from conftest import SAME_ORIGIN
from users import tokens
from users.models import RefreshToken, User
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery"
COOKIE = django_settings.REFRESH_COOKIE_NAME


def link_params(message):
    """Query parameters of the application link in an email."""
    url = re.search(r"http://\S+", message.body).group()
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def actions(user):
    return list(
        AuditLog.objects.filter(target_id=user.pk)
        .order_by("created_at")
        .values_list("action", flat=True)
    )


def login(api, user, password=PASSWORD):
    return api.post("/api/v1/auth/login/", {"email": user.email, "password": password})


def refresh(api, **overrides):
    return api.post("/api/v1/auth/refresh/", headers={**SAME_ORIGIN, **overrides})


# --- Registration and email verification ----------------------------------------------


def register(api, **overrides):
    body = {"email": "ada@example.com", "password": PASSWORD, "display_name": "Ada Lovelace"}
    return api.post("/api/v1/auth/register/", {**body, **overrides})


def test_register_creates_an_unverified_user_with_a_profile(
    api, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = register(api, email="  Ada@Example.com ")

    assert response.status_code == 202
    user = User.objects.get(email="ada@example.com")
    assert not user.is_email_verified
    assert user.check_password(PASSWORD)
    assert user.profile.display_name == "Ada Lovelace"
    assert actions(user) == ["user.registered"]
    assert [m.to for m in mail.outbox] == [["ada@example.com"]]
    assert COOKIE not in response.cookies  # registering does not sign the user in


def test_register_does_not_reveal_an_existing_account(api, django_capture_on_commit_callbacks):
    UserFactory(email="ada@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        fresh = register(api, email="new@example.com")
    existing = register(api)

    assert existing.status_code == fresh.status_code == 202
    assert existing.json() == fresh.json()
    assert User.objects.filter(email="ada@example.com").count() == 1
    assert mail.outbox[-1].subject == "You already have an account"


def test_registering_again_before_verifying_resends_the_link(api):
    user = UserFactory(email="ada@example.com", unverified=True)

    assert register(api, password="a-different-passphrase").status_code == 202

    assert mail.outbox[-1].subject == "Confirm your email address"
    user.refresh_from_db()
    assert user.check_password(PASSWORD)  # the second attempt cannot change the password


@pytest.mark.parametrize("password", ["short", "1234567890123", "password123"])
def test_register_rejects_weak_passwords(api, password):
    response = register(api, password=password)

    assert response.status_code == 422
    assert response.json()["code"] == "weak_password"
    assert "password" in response.json()["errors"]
    assert not User.objects.exists()


def test_register_validates_input(api):
    response = api.post("/api/v1/auth/register/", {"email": "not-an-email"})

    assert response.status_code == 400
    assert set(response.json()["errors"]) == {"email", "password", "display_name"}


def test_verify_email_is_idempotent(api, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        register(api)
    token = link_params(mail.outbox[0])["token"]

    first = api.post("/api/v1/auth/verify-email/", {"token": token})
    second = api.post("/api/v1/auth/verify-email/", {"token": token})

    assert first.status_code == second.status_code == 204
    user = User.objects.get(email="ada@example.com")
    assert user.is_email_verified
    assert actions(user) == ["user.registered", "user.email_verified"]


def test_verify_email_rejects_bad_and_expired_tokens(api, settings):
    user = UserFactory(unverified=True)
    token = tokens.make_email_verification_token(user)

    tampered = api.post("/api/v1/auth/verify-email/", {"token": token[:-2] + "xx"})
    settings.EMAIL_VERIFICATION_MAX_AGE = timedelta(0)
    expired = api.post("/api/v1/auth/verify-email/", {"token": token})

    assert (tampered.status_code, tampered.json()["code"]) == (400, "token_invalid")
    assert (expired.status_code, expired.json()["code"]) == (400, "token_expired")
    user.refresh_from_db()
    assert not user.is_email_verified


def test_verification_token_is_bound_to_the_address(api):
    user = UserFactory(unverified=True)
    token = tokens.make_email_verification_token(user)
    User.objects.filter(pk=user.pk).update(email="changed@example.com")

    assert api.post("/api/v1/auth/verify-email/", {"token": token}).status_code == 400


def test_resend_verification_is_uniform(api):
    unverified = UserFactory(unverified=True)
    verified = UserFactory()
    url = "/api/v1/auth/verify-email/resend/"

    responses = [
        api.post(url, {"email": email})
        for email in (unverified.email, verified.email, "nobody@example.com")
    ]

    assert {r.status_code for r in responses} == {202}
    assert len({r.content for r in responses}) == 1
    assert [m.to for m in mail.outbox] == [[unverified.email]]


# --- Login ----------------------------------------------------------------------------


def test_login_returns_an_access_token_and_sets_the_refresh_cookie(api, api_as):
    user = UserFactory()

    response = login(api, user)

    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] == 600
    assert body["user"]["email"] == user.email
    assert tokens.read_access_token(body["access_token"]) == user.pk
    cookie = response.cookies[COOKIE]
    assert cookie["httponly"]
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api/v1/auth/"
    assert cookie["secure"]
    # Only a hash is stored.
    stored = RefreshToken.objects.get(user=user)
    assert stored.token_hash == tokens.hash_refresh_token(cookie.value)
    assert cookie.value not in str(stored.__dict__)
    user.refresh_from_db()
    assert user.last_login is not None
    assert actions(user) == ["user.logged_in"]


def test_login_failures_are_indistinguishable(api):
    active = UserFactory()
    inactive = UserFactory(is_active=False)

    responses = [
        login(api, active, "wrong-password"),
        login(api, inactive),
        api.post("/api/v1/auth/login/", {"email": "nobody@example.com", "password": PASSWORD}),
    ]

    assert {r.status_code for r in responses} == {401}
    assert {r.json()["code"] for r in responses} == {"invalid_credentials"}
    assert len({r.json()["detail"] for r in responses}) == 1
    assert all(COOKIE not in r.cookies for r in responses)
    assert not RefreshToken.objects.exists()


def test_unverified_users_can_sign_in(api):
    assert login(api, UserFactory(unverified=True)).status_code == 200


def test_login_locks_an_address_after_repeated_failures(api, settings):
    settings.LOGIN_FAILURE_LIMIT = 3
    user = UserFactory()
    for _ in range(3):
        assert login(api, user, "wrong-password").status_code == 401

    locked = login(api, user)

    assert locked.status_code == 429
    assert int(locked["Retry-After"]) > 0
    assert login(api, UserFactory()).status_code == 200  # other accounts are unaffected


def test_successful_login_resets_the_failure_count(api, settings):
    settings.LOGIN_FAILURE_LIMIT = 3
    user = UserFactory()
    for _ in range(2):
        login(api, user, "wrong-password")
    login(api, user)
    for _ in range(2):
        login(api, user, "wrong-password")

    assert login(api, user).status_code == 200


def test_login_is_rate_limited_per_client_address(api, settings, monkeypatch):
    settings.TRUST_PROXY_HEADERS = True
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "auth_login", "2/min")
    user = UserFactory()

    def attempt(ip):
        return api.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": PASSWORD},
            headers={"X-Real-IP": ip},
        )

    assert [attempt("203.0.113.1").status_code for _ in range(3)] == [200, 200, 429]
    assert attempt("203.0.113.2").status_code == 200


# --- Refresh --------------------------------------------------------------------------


def test_refresh_rotates_the_token(api):
    user = UserFactory()
    first = login(api, user).cookies[COOKIE].value

    response = refresh(api)

    assert response.status_code == 200
    assert tokens.read_access_token(response.json()["access_token"]) == user.pk
    second = response.cookies[COOKIE].value
    assert second != first
    old, new = RefreshToken.objects.filter(user=user).order_by("created_at")
    assert old.rotated_at is not None
    assert new.rotated_at is None
    assert old.family == new.family


def test_reusing_a_rotated_token_revokes_the_whole_session(api, settings):
    settings.REFRESH_TOKEN_REUSE_GRACE = timedelta(0)
    user = UserFactory()
    stolen = login(api, user).cookies[COOKIE].value
    assert refresh(api).status_code == 200  # the legitimate client rotates
    current = api.cookies[COOKIE].value

    api.cookies[COOKIE] = stolen
    reuse = refresh(api)
    api.cookies[COOKIE] = current
    after = refresh(api)

    assert (reuse.status_code, reuse.json()["code"]) == (401, "session_expired")
    assert after.status_code == 401
    assert not RefreshToken.objects.filter(user=user, revoked_at__isnull=True).exists()
    assert "user.refresh_token_reused" in actions(user)


def test_a_just_rotated_token_still_works_within_the_grace_window(api):
    user = UserFactory()
    original = login(api, user).cookies[COOKIE].value
    assert refresh(api).status_code == 200

    api.cookies[COOKIE] = original  # a second tab that had not yet received the new cookie
    assert refresh(api).status_code == 200
    assert not RefreshToken.objects.filter(user=user, revoked_at__isnull=False).exists()


def test_reuse_in_one_session_leaves_other_sessions_alone(api, settings):
    settings.REFRESH_TOKEN_REUSE_GRACE = timedelta(0)
    user = UserFactory()
    stolen = login(api, user).cookies[COOKIE].value
    refresh(api)
    other_device = login(api, user).cookies[COOKIE].value

    api.cookies[COOKIE] = stolen
    assert refresh(api).status_code == 401
    api.cookies[COOKIE] = other_device
    assert refresh(api).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": None},
        {"X-Requested-With": None},
        {"Origin": "https://evil.example"},
    ],
)
def test_refresh_requires_a_same_origin_request(api, headers):
    login(api, UserFactory())
    sent = {k: v for k, v in {**SAME_ORIGIN, **headers}.items() if v is not None}

    response = api.post("/api/v1/auth/refresh/", headers=sent)

    assert (response.status_code, response.json()["code"]) == (403, "cross_origin_denied")
    assert RefreshToken.objects.filter(rotated_at__isnull=True).count() == 1


def test_refresh_accepts_a_configured_trusted_origin(api, settings):
    settings.CSRF_TRUSTED_ORIGINS = ["https://app.example"]
    login(api, UserFactory())

    assert refresh(api, Origin="https://app.example").status_code == 200


def test_refresh_fails_without_a_usable_token(api):
    user = UserFactory()
    missing = refresh(api)
    login(api, user)
    RefreshToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    expired = refresh(api)

    assert (missing.status_code, missing.json()["code"]) == (401, "session_expired")
    assert expired.status_code == 401
    assert expired.cookies[COOKIE].value == ""  # the dead cookie is cleared


def test_refresh_fails_for_a_deactivated_user(api):
    user = UserFactory()
    login(api, user)
    User.objects.filter(pk=user.pk).update(is_active=False)

    assert refresh(api).status_code == 401


# --- Logout ---------------------------------------------------------------------------


def test_logout_ends_the_session(api):
    user = UserFactory()
    token = login(api, user).cookies[COOKIE].value

    response = api.post("/api/v1/auth/logout/", headers=SAME_ORIGIN)

    assert response.status_code == 204
    assert response.cookies[COOKIE].value == ""
    api.cookies[COOKIE] = token
    assert refresh(api).status_code == 401
    assert actions(user) == ["user.logged_in", "user.logged_out"]


def test_logout_without_a_session_succeeds(api):
    assert api.post("/api/v1/auth/logout/", headers=SAME_ORIGIN).status_code == 204
    assert api.post("/api/v1/auth/logout/").status_code == 403


# --- Access tokens --------------------------------------------------------------------


def test_protected_endpoints_require_an_access_token(api):
    response = api.get("/api/v1/users/me/")

    assert (response.status_code, response.json()["code"]) == (401, "not_authenticated")
    assert response["WWW-Authenticate"] == "Bearer"


def test_access_token_is_accepted(api_as):
    user = UserFactory()

    assert api_as(user).get("/api/v1/users/me/").json()["id"] == str(user.pk)


def test_expired_and_forged_access_tokens_are_rejected(api, settings):
    user = UserFactory()
    valid, _ = tokens.make_access_token(user)
    settings.ACCESS_TOKEN_LIFETIME = timedelta(seconds=-1)
    expired, _ = tokens.make_access_token(user)
    refresh_token, _ = tokens.new_refresh_token()

    for bad in (expired, valid[:-3] + "abc", refresh_token, "not-a-token", "a b"):
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {bad}")
        response = api.get("/api/v1/users/me/")
        assert (response.status_code, response.json()["code"]) == (401, "authentication_failed")


def test_access_token_stops_working_when_the_user_is_deactivated(api_as):
    user = UserFactory()
    client = api_as(user)
    User.objects.filter(pk=user.pk).update(is_active=False)

    assert client.get("/api/v1/users/me/").status_code == 401


def test_public_auth_endpoints_ignore_a_stale_authorization_header(api):
    user = UserFactory()
    api.credentials(HTTP_AUTHORIZATION="Bearer expired-or-garbage")

    assert login(api, user).status_code == 200


# --- Password reset and change --------------------------------------------------------


def request_reset(api, email):
    return api.post("/api/v1/auth/password-reset/", {"email": email})


def test_password_reset_request_is_uniform(api):
    user = UserFactory()

    known = request_reset(api, user.email.upper())
    unknown = request_reset(api, "nobody@example.com")

    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content
    assert [m.to for m in mail.outbox] == [[user.email]]
    assert actions(user) == ["user.password_reset_requested"]


def test_password_reset_sets_the_password_once_and_ends_sessions(api):
    user = UserFactory(unverified=True)
    login(api, user)
    request_reset(api, user.email)
    params = link_params(mail.outbox[-1])
    body = {**params, "new_password": "a-brand-new-passphrase"}

    first = api.post("/api/v1/auth/password-reset/confirm/", body)
    second = api.post("/api/v1/auth/password-reset/confirm/", body)

    assert first.status_code == 204
    assert (second.status_code, second.json()["code"]) == (400, "token_invalid")
    assert refresh(api).status_code == 401  # the session from before the reset is gone
    assert login(api, user).status_code == 401
    assert login(api, user, "a-brand-new-passphrase").status_code == 200
    user.refresh_from_db()
    assert user.is_email_verified  # the link proved control of the mailbox


def test_password_reset_rejects_bad_links_and_weak_passwords(api):
    user = UserFactory()
    request_reset(api, user.email)
    params = link_params(mail.outbox[-1])
    url = "/api/v1/auth/password-reset/confirm/"

    weak = api.post(url, {**params, "new_password": "short"})
    bad_token = api.post(url, {**params, "token": "nope", "new_password": "a-new-passphrase-1"})
    bad_uid = api.post(url, {**params, "uid": "nope", "new_password": "a-new-passphrase-1"})

    assert (weak.status_code, list(weak.json()["errors"])) == (422, ["new_password"])
    assert bad_token.status_code == bad_uid.status_code == 400
    assert login(api, user).status_code == 200


def test_password_reset_lifts_a_login_lockout(api, settings):
    settings.LOGIN_FAILURE_LIMIT = 2
    user = UserFactory()
    for _ in range(2):
        login(api, user, "wrong-password")
    request_reset(api, user.email)
    body = {**link_params(mail.outbox[-1]), "new_password": "a-brand-new-passphrase"}
    api.post("/api/v1/auth/password-reset/confirm/", body)

    assert login(api, user, "a-brand-new-passphrase").status_code == 200


def test_password_change_ends_other_sessions_and_keeps_this_one(api, api_as):
    user = UserFactory()
    other_device = login(api, user).cookies[COOKIE].value
    client = api_as(user)

    wrong = client.post(
        "/api/v1/auth/password-change/",
        {"current_password": "wrong-password", "new_password": "a-brand-new-passphrase"},
    )
    changed = client.post(
        "/api/v1/auth/password-change/",
        {"current_password": PASSWORD, "new_password": "a-brand-new-passphrase"},
    )

    assert (wrong.status_code, list(wrong.json()["errors"])) == (422, ["current_password"])
    assert changed.status_code == 200
    api.cookies[COOKIE] = other_device
    assert refresh(api).status_code == 401
    assert refresh(client).status_code == 200  # the cookie issued by the change
    assert login(api, user, "a-brand-new-passphrase").status_code == 200


def test_password_change_requires_authentication(api):
    response = api.post(
        "/api/v1/auth/password-change/",
        {"current_password": PASSWORD, "new_password": "a-brand-new-passphrase"},
    )

    assert response.status_code == 401
