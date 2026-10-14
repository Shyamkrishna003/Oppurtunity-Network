"""Protections that apply to every endpoint: the backstop rate limit, response headers,
and the checks production settings must pass."""

from typing import Any

import pytest
from rest_framework.throttling import SimpleRateThrottle

from common.middleware import DATA_CONTENT_SECURITY_POLICY
from config.settings.guards import production_problems
from opportunities.tests.factories import make_job
from users.tests.factories import UserFactory

SECRET = "k9$Tq2!vX7@pL4#mZ8^wB1&nC5*eR3(yU6)hJ0-dF_gA+sQ=oIiW"
SAFE: dict[str, Any] = {
    "secret_key": SECRET,
    "allowed_hosts": ["opportunity.example"],
    "frontend_url": "https://opportunity.example",
    "refresh_cookie_secure": True,
    "trust_proxy_headers": True,
}


@pytest.fixture
def tight(monkeypatch):
    """Limits small enough to reach in a test. Patched on the class, where DRF keeps the
    rates once it has read them, and put back afterwards."""
    rates = {**SimpleRateThrottle.THROTTLE_RATES, "api_anon": "3/min", "api_user": "5/min"}
    monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", rates)


@pytest.mark.django_db
def test_every_endpoint_has_a_limit_even_without_its_own(tight, api, api_as):
    # Reading one opportunity: open to visitors, and with no limit of its own.
    url = f"/api/v1/opportunities/{make_job(status='PUBLISHED').pk}/"
    user, other = UserFactory.create(), UserFactory.create()

    assert [api.get(url).status_code for _ in range(4)] == [200, 200, 200, 429]

    # Someone signed in gets more, counted on their own account and not on the address.
    assert [api_as(user).get(url).status_code for _ in range(6)] == [200] * 5 + [429]
    throttled = api_as(user).get(url)
    assert throttled.json()["code"] == "throttled"
    assert "Retry-After" in throttled.headers
    assert api_as(other).get(url).status_code == 200


@pytest.mark.django_db
def test_the_default_limits_leave_room_for_ordinary_use(api_as):
    url = f"/api/v1/opportunities/{make_job(status='PUBLISHED').pk}/"
    client = api_as(UserFactory.create())

    assert {client.get(url).status_code for _ in range(60)} == {200}


@pytest.mark.django_db
def test_api_responses_cannot_be_rendered_as_pages(api):
    response = api.get("/api/v1/opportunities/")

    assert response.headers["Content-Security-Policy"] == DATA_CONTENT_SECURITY_POLICY
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert (
        "default-src 'none'" in api.get("/api/v1/no-such-thing/").headers["Content-Security-Policy"]
    )
    # Not on pages the server renders itself, which need their own styles and scripts.
    assert "Content-Security-Policy" not in api.get("/admin/login/").headers


def test_safe_production_values_pass():
    assert production_problems(**SAFE) == []


@pytest.mark.parametrize(
    ("unsafe", "named"),
    [
        ({"secret_key": "dev-only-not-a-secret"}, "DJANGO_SECRET_KEY"),
        ({"secret_key": "a" * 60}, "DJANGO_SECRET_KEY"),
        ({"secret_key": "dev-only-" + SECRET}, "DJANGO_SECRET_KEY"),
        ({"allowed_hosts": []}, "DJANGO_ALLOWED_HOSTS"),
        ({"allowed_hosts": ["*"]}, "DJANGO_ALLOWED_HOSTS"),
        ({"frontend_url": "http://opportunity.example"}, "FRONTEND_URL"),
        ({"refresh_cookie_secure": False}, "AUTH_COOKIE_SECURE"),
        ({"trust_proxy_headers": False}, "TRUST_PROXY_HEADERS"),
    ],
)
def test_unsafe_production_values_are_named(unsafe, named):
    (problem,) = production_problems(**{**SAFE, **unsafe})

    assert named in problem
