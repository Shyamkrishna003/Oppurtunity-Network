import pytest
from django.core.cache import cache

from common import metrics
from common.tasks import ping
from opportunities.tests.factories import make_job

URL = "/metrics"
TOKEN = "scrape-me-if-you-can"


@pytest.fixture(autouse=True)
def _fresh():
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
def scrape(client, settings):
    """Fetch the metrics as an authorised scraper would, and return the text."""
    settings.METRICS_TOKEN = TOKEN

    def get() -> str:
        response = client.get(URL, headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/plain")
        text: str = response.content.decode()
        return text

    return get


def test_the_endpoint_is_off_unless_a_token_is_configured(client, settings):
    settings.METRICS_TOKEN = ""

    assert client.get(URL).status_code == 404
    assert client.get(URL, headers={"Authorization": "Bearer "}).status_code == 404


@pytest.mark.parametrize("presented", ["", "Bearer wrong", f"Basic {TOKEN}", TOKEN, "Bearer"])
def test_the_endpoint_needs_the_token(client, settings, presented):
    settings.METRICS_TOKEN = TOKEN

    response = client.get(URL, headers={"Authorization": presented})

    assert response.status_code == 401
    assert b"http_requests_total" not in response.content


def test_a_scraper_reaches_it_by_any_host_name_over_plain_http(client, settings):
    # Inside the network the server is "backend:8000", which is not one of the site's names.
    settings.METRICS_TOKEN = TOKEN
    settings.ALLOWED_HOSTS = ["opportunity.example"]
    settings.SECURE_SSL_REDIRECT = True

    response = client.get(URL, headers={"Authorization": f"Bearer {TOKEN}", "Host": "backend:8000"})

    assert response.status_code == 200


@pytest.mark.django_db
def test_requests_are_counted_by_route_and_never_by_path(api, scrape):
    first, second = make_job(status="PUBLISHED"), make_job(status="PUBLISHED")
    api.get(f"/api/v1/opportunities/{first.pk}/")
    api.get(f"/api/v1/opportunities/{second.pk}/")
    api.get("/api/v1/users/me/")
    api.get("/api/v1/no-such-thing/")
    api.get("/healthz")

    text = scrape()

    detail = 'method="GET",route="api/v1/opportunities/<uuid:opportunity_id>/"'
    assert f'http_requests_total{{{detail},status="200"}} 2' in text
    assert f"http_request_duration_seconds_count{{{detail}}} 2" in text
    assert f'http_request_duration_seconds_bucket{{{detail},le="+Inf"}} 2' in text
    assert 'route="api/v1/users/me/",status="401"} 1' in text
    # No ID ever becomes a label, and health checks and scrapes are not counted.
    assert str(first.pk) not in text
    assert "healthz" not in text
    assert 'route="metrics"' not in scrape()


def test_histogram_buckets_are_cumulative():
    metrics.record_request("GET", "a/", 200, 0.07)
    metrics.record_request("GET", "a/", 200, 0.3)
    metrics.record_request("GET", "a/", 500, 9.0)

    text = metrics.render()

    def bucket(le: str) -> str:
        return f'http_request_duration_seconds_bucket{{method="GET",route="a/",le="{le}"}}'

    assert f"{bucket('0.05')} 0" in text
    assert f"{bucket('0.1')} 1" in text
    assert f"{bucket('0.5')} 2" in text
    assert f"{bucket('5.0')} 2" in text
    assert f"{bucket('+Inf')} 3" in text
    assert 'http_request_duration_seconds_sum{method="GET",route="a/"} 9.370000' in text
    assert 'http_requests_total{method="GET",route="a/",status="500"} 1' in text


def test_background_tasks_are_counted_wherever_they_ran(scrape):
    cache.clear()
    ping.delay()
    ping.delay()
    metrics.record_task("common.ping", succeeded=False, seconds=1.5)

    text = scrape()

    assert 'celery_tasks_total{task="common.ping",outcome="succeeded"} 2' in text
    assert 'celery_tasks_total{task="common.ping",outcome="failed"} 1' in text
    assert 'celery_task_duration_seconds_sum{task="common.ping"}' in text
    # A task that has never run has no line, rather than a misleading zero.
    assert 'task="opportunities.expire_due"' not in text


@pytest.mark.django_db
def test_gauges_are_read_when_asked_and_one_failing_does_not_hide_the_rest(scrape):
    metrics.socket_opened()
    metrics.socket_opened()
    metrics.socket_closed()

    def broken() -> float:
        raise RuntimeError("cannot be read")

    metrics.gauge("test_broken", "Always fails.", broken)
    metrics.gauge("test_answer", "Always 42.", lambda: 42.0)
    try:
        text = scrape()
    finally:
        metrics._gauges.pop("test_broken")
        metrics._gauges.pop("test_answer")

    assert "websocket_connections 1" in text
    assert "test_answer 42.0" in text
    assert "test_broken" not in text
    assert "notification_emails_pending 0.0" in text


def test_label_values_are_escaped():
    metrics.record_request("GET", 'odd"route\\with\nbreaks', 200, 0.01)

    assert 'route="odd\\"route\\\\with\\nbreaks"' in metrics.render()
