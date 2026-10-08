import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.urls("common.tests.urls")

ENVELOPE_KEYS = {"type", "title", "status", "code", "detail", "errors", "request_id"}


@pytest.fixture
def client():
    return APIClient(raise_request_exception=False)


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/http404/", 404, "not_found"),
        ("/django-denied/", 403, "permission_denied"),
        ("/protected/", 401, "not_authenticated"),
        ("/throttled/", 429, "throttled"),
        ("/transition/", 409, "invalid_transition"),
        ("/rule/", 422, "deadline_passed"),
        ("/api/v1/does-not-exist/", 404, "not_found"),
    ],
)
def test_errors_use_the_envelope(client, path, status, code):
    response = client.get(path)

    assert response.status_code == status
    body = response.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"urn:opportunity-network:error:{code}"
    assert body["request_id"] == response["X-Request-ID"]


def test_validation_errors_are_flattened_per_field(client):
    response = client.post(
        "/validate/", {"title": "too long", "items": [{"name": "ok"}, {}]}, format="json"
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body["errors"]) == {"title", "items.1.name"}
    assert body["errors"]["items.1.name"] == ["This field is required."]


def test_business_rule_violation_carries_field_errors(client):
    body = client.get("/rule/").json()

    assert body["detail"] == "Deadline has passed."
    assert body["errors"] == {"deadline": ["Too late."]}


def test_throttled_sets_retry_after(client):
    assert client.get("/throttled/")["Retry-After"] == "13"


def test_unhandled_exceptions_do_not_leak_details(client):
    response = client.get("/boom/")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "error"
    assert "secret internals" not in response.content.decode()


def test_unhandled_exceptions_propagate_in_debug(client, settings):
    settings.DEBUG = True

    with pytest.raises(RuntimeError):
        APIClient().get("/boom/")
