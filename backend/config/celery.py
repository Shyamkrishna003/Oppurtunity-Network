import os
import time
from typing import Any

import structlog
from celery import Celery, Task, states
from celery.signals import before_task_publish, task_postrun, task_prerun

from common import metrics, request_context

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@before_task_publish.connect
def propagate_request_id(headers: dict[str, Any], **kwargs: Any) -> None:
    # Carries the originating HTTP request's ID into the task so logs can be correlated.
    request_id = request_context.get_request_id()
    if request_id:
        headers.setdefault("request_id", request_id)


@task_prerun.connect
def bind_task_context(task_id: str, task: Task[Any, Any], **kwargs: Any) -> None:
    # Eager tasks run inside the caller's context; leave that context intact.
    if task.request.is_eager:
        return
    request_context.bind(request_id=getattr(task.request, "request_id", None) or "")
    structlog.contextvars.bind_contextvars(task_id=task_id, task_name=task.name)


@task_postrun.connect
def clear_task_context(task: Task[Any, Any], **kwargs: Any) -> None:
    if not task.request.is_eager:
        request_context.clear()


# --- Metrics -------------------------------------------------------------------------------

_started: dict[str, float] = {}


@task_prerun.connect
def note_task_start(task_id: str, **kwargs: Any) -> None:
    _started[task_id] = time.monotonic()


@task_postrun.connect
def count_task(task_id: str, task: Task[Any, Any], state: str | None = None, **kwargs: Any) -> None:
    started = _started.pop(task_id, None)
    metrics.record_task(
        task.name,
        succeeded=state == states.SUCCESS,
        seconds=time.monotonic() - started if started is not None else 0.0,
    )


def _waiting_tasks() -> float:
    """Tasks queued and not yet picked up, across every queue. With a Redis broker each
    queue is a list, so its length is the backlog."""
    with app.connection_or_acquire() as connection:
        client = connection.default_channel.client
        return float(sum(client.llen(queue) for queue in QUEUES))


QUEUES = ("default", "email", "notifications", "scheduled", "analytics")
metrics.gauge("celery_queue_length", "Background tasks waiting to be picked up.", _waiting_tasks)
