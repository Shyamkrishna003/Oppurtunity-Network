import re

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from common import request_context
from common.middleware import RequestContextMiddleware


def _run(request):
    seen = {}

    def view(req):
        seen["request_id"] = request_context.get_request_id()
        seen["client_ip"] = request_context.get_client_ip()
        return HttpResponse()

    response = RequestContextMiddleware(view)(request)
    return response, seen


def test_generates_a_request_id_and_returns_it():
    response, seen = _run(RequestFactory().get("/anything"))

    assert re.fullmatch(r"[0-9a-f]{32}", response["X-Request-ID"])
    assert seen["request_id"] == response["X-Request-ID"]


def test_reuses_a_well_formed_incoming_id():
    response, _ = _run(RequestFactory().get("/", headers={"X-Request-ID": "abc-123_DEF456"}))

    assert response["X-Request-ID"] == "abc-123_DEF456"


@pytest.mark.parametrize("bad", ["short", "x" * 65, "has space in it", "new\nline-injected"])
def test_replaces_a_malformed_incoming_id(bad):
    response, _ = _run(RequestFactory().get("/", headers={"X-Request-ID": bad}))

    assert response["X-Request-ID"] != bad


def test_context_is_cleared_after_the_request():
    _run(RequestFactory().get("/"))

    assert request_context.get_request_id() == ""
    assert request_context.get_client_ip() is None


def test_proxy_header_is_ignored_unless_trusted(settings):
    request = RequestFactory().get("/", headers={"X-Real-IP": "203.0.113.9"})

    settings.TRUST_PROXY_HEADERS = False
    assert _run(request)[1]["client_ip"] == "127.0.0.1"

    settings.TRUST_PROXY_HEADERS = True
    assert _run(request)[1]["client_ip"] == "203.0.113.9"
