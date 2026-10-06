from common import request_context
from common.tasks import ping
from config.celery import propagate_request_id


def test_ping_runs():
    assert ping() == "pong"
    ping.delay()  # eager in tests: raises if the task fails


def test_request_id_is_added_to_published_task_headers():
    request_context.bind(request_id="req-12345678")
    headers: dict[str, str] = {}
    try:
        propagate_request_id(headers=headers)
    finally:
        request_context.clear()

    assert headers == {"request_id": "req-12345678"}


def test_no_header_outside_a_request():
    headers: dict[str, str] = {}

    propagate_request_id(headers=headers)

    assert headers == {}
