from typing import Any

import structlog
from celery import Task, shared_task
from kombu.exceptions import OperationalError

logger = structlog.get_logger(__name__)


def enqueue(task: Task[..., Any], *args: Any) -> None:
    """Queue a task for work that follows a change which has already been committed.

    A broker outage is logged, not raised: failing the request would tell the user the
    change did not happen when it did. Only use for work that can be requested again.
    """
    try:
        task.delay(*args)
    except OperationalError:
        logger.exception("task_enqueue_failed", task=task.name)


@shared_task(name="common.ping")
def ping() -> str:
    logger.info("ping")
    return "pong"
