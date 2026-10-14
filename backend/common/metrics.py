"""Numbers about the running system, in the text format Prometheus scrapes.

Three kinds, kept where each can be counted correctly:

- requests are counted in the server process that served them (each server is scraped);
- background tasks run in separate worker processes, so their counts go to the shared
  cache, where any server can read them;
- gauges (queue depth, open sockets, anything an app registers) are read when asked.

Counters start again from zero when a process or the cache restarts, which is what
Prometheus expects of a counter.
"""

import threading
from collections import defaultdict
from collections.abc import Callable, Iterable

import structlog
from django.core.cache import cache

logger = structlog.get_logger(__name__)

# Upper bounds, in seconds, of the request-duration histogram.
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

_lock = threading.Lock()
# (method, route, status) -> count; (method, route) -> per-bucket counts, sum, count.
_requests: dict[tuple[str, str, str], int] = defaultdict(int)
_durations: dict[tuple[str, str], list[float]] = {}
_open_sockets = 0
# name -> (help text, function returning the value now)
_gauges: dict[str, tuple[str, Callable[[], float]]] = {}

_TASK_KEY = "metrics:task:{name}:{what}"
_TASK_COUNTS = ("succeeded", "failed", "milliseconds")


def record_request(method: str, route: str, status: int, seconds: float) -> None:
    """Count one finished request. ``route`` is the URL pattern, never the path itself:
    a label per opportunity ID would grow without end."""
    with _lock:
        _requests[(method, route, str(status))] += 1
        series = _durations.setdefault((method, route), [0.0] * (len(BUCKETS) + 2))
        for index, bound in enumerate(BUCKETS):
            if seconds <= bound:
                series[index] += 1
        series[-2] += seconds
        series[-1] += 1


def socket_opened() -> None:
    global _open_sockets
    with _lock:
        _open_sockets += 1


def socket_closed() -> None:
    global _open_sockets
    with _lock:
        _open_sockets = max(0, _open_sockets - 1)


def record_task(name: str, *, succeeded: bool, seconds: float) -> None:
    """Count one finished background task. Never raises: a task must not fail because it
    could not be counted."""
    try:
        for what, amount in (
            ("succeeded" if succeeded else "failed", 1),
            ("milliseconds", round(seconds * 1000)),
        ):
            key = _TASK_KEY.format(name=name, what=what)
            cache.add(key, 0, timeout=None)
            cache.incr(key, amount)
    except Exception:
        logger.warning("task_metric_failed", task=name, exc_info=True)


def gauge(name: str, help_text: str, read: Callable[[], float]) -> None:
    """Register a value to be read whenever metrics are asked for. Called by the app that
    owns the number, so this module needs to know nothing about it."""
    _gauges[name] = (help_text, read)


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**labels: str) -> str:
    return "{" + ",".join(f'{key}="{_label(value)}"' for key, value in labels.items()) + "}"


def _request_lines() -> Iterable[str]:
    with _lock:
        requests = dict(_requests)
        durations = {key: list(series) for key, series in _durations.items()}
    yield "# HELP http_requests_total Requests finished, by method, route and status."
    yield "# TYPE http_requests_total counter"
    for (method, route, status), count in sorted(requests.items()):
        yield f"http_requests_total{_labels(method=method, route=route, status=status)} {count}"
    yield "# HELP http_request_duration_seconds How long requests took."
    yield "# TYPE http_request_duration_seconds histogram"
    for (method, route), series in sorted(durations.items()):
        for bound, reached in zip(BUCKETS, series, strict=False):
            labels = _labels(method=method, route=route, le=str(bound))
            yield f"http_request_duration_seconds_bucket{labels} {int(reached)}"
        labels = _labels(method=method, route=route, le="+Inf")
        yield f"http_request_duration_seconds_bucket{labels} {int(series[-1])}"
        plain = _labels(method=method, route=route)
        yield f"http_request_duration_seconds_sum{plain} {series[-2]:.6f}"
        yield f"http_request_duration_seconds_count{plain} {int(series[-1])}"


def _task_lines(task_names: Iterable[str]) -> Iterable[str]:
    names = sorted(task_names)
    keys = {
        _TASK_KEY.format(name=name, what=what): (name, what)
        for name in names
        for what in _TASK_COUNTS
    }
    counted: dict[tuple[str, str], int] = {
        keys[key]: value for key, value in cache.get_many(list(keys)).items()
    }
    yield "# HELP celery_tasks_total Background tasks finished, by task and outcome."
    yield "# TYPE celery_tasks_total counter"
    for name in names:
        for outcome in ("succeeded", "failed"):
            if (name, outcome) in counted:
                labels = _labels(task=name, outcome=outcome)
                yield f"celery_tasks_total{labels} {counted[(name, outcome)]}"
    yield "# HELP celery_task_duration_seconds_sum Time spent running each task."
    yield "# TYPE celery_task_duration_seconds_sum counter"
    for name in names:
        if (name, "milliseconds") in counted:
            seconds = counted[(name, "milliseconds")] / 1000
            yield f"celery_task_duration_seconds_sum{_labels(task=name)} {seconds:.3f}"


def _gauge_lines() -> Iterable[str]:
    yield "# HELP websocket_connections Live connections open on this server."
    yield "# TYPE websocket_connections gauge"
    yield f"websocket_connections {_open_sockets}"
    for name, (help_text, read) in sorted(_gauges.items()):
        try:
            value = read()
        except Exception:
            # One number that cannot be read must not hide all the others.
            logger.warning("gauge_failed", gauge=name, exc_info=True)
            continue
        yield f"# HELP {name} {help_text}"
        yield f"# TYPE {name} gauge"
        yield f"{name} {value}"


def render(task_names: Iterable[str] = ()) -> str:
    """Everything, as one Prometheus text exposition."""
    lines = [*_request_lines(), *_task_lines(task_names), *_gauge_lines()]
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Forget what this process has counted. For tests."""
    global _open_sockets
    with _lock:
        _requests.clear()
        _durations.clear()
        _open_sockets = 0
