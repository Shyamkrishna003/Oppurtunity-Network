from collections.abc import Callable

import structlog
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_safe

logger = structlog.get_logger(__name__)


def _check_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _check_cache() -> None:
    cache.set("readyz", "1", timeout=5)
    if cache.get("readyz") != "1":
        raise RuntimeError("cache round-trip failed")


def _check_migrations() -> None:
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise RuntimeError("unapplied migrations")


CHECKS: dict[str, Callable[[], None]] = {
    "database": _check_database,
    "cache": _check_cache,
    "migrations": _check_migrations,
}


@require_safe
def liveness(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_safe
def readiness(request: HttpRequest) -> JsonResponse:
    results: dict[str, str] = {}
    for name, check in CHECKS.items():
        try:
            check()
        except Exception:
            # The endpoint is unauthenticated: report which dependency failed, never why.
            logger.warning("readiness_check_failed", check=name, exc_info=True)
            results[name] = "error"
        else:
            results[name] = "ok"

    ready = all(result == "ok" for result in results.values())
    return JsonResponse(
        {"status": "ok" if ready else "unavailable", "checks": results},
        status=200 if ready else 503,
    )
