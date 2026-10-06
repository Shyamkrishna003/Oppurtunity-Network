import pytest
from django.test import Client

from common import health


def test_liveness_needs_no_dependencies():
    response = Client().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readiness_reports_every_check():
    response = Client().get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "cache": "ok", "migrations": "ok"},
    }


@pytest.mark.django_db
def test_readiness_fails_without_exposing_the_cause(monkeypatch):
    def broken():
        raise RuntimeError("redis://user:password@host is down")

    monkeypatch.setitem(health.CHECKS, "cache", broken)

    response = Client().get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "ok", "cache": "error", "migrations": "ok"},
    }
    assert "password" not in response.content.decode()


def test_health_endpoints_reject_writes():
    assert Client().post("/healthz").status_code == 405
