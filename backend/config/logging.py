from typing import Any

import structlog

_SHARED_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
]


def build_logging(*, json_logs: bool, level: str) -> dict[str, Any]:
    """Configure structlog and return the matching Django ``LOGGING`` dict.

    Both structlog loggers and stdlib loggers (Django, Celery, third parties) are rendered
    by the same formatter, so every line carries the bound request/task context.
    """
    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: Any = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    processors: list[Any] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if json_logs:
        processors.append(structlog.processors.format_exc_info)
    processors.append(renderer)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structured": {
                "()": structlog.stdlib.ProcessorFormatter,
                "foreign_pre_chain": _SHARED_PROCESSORS,
                "processors": processors,
            },
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "structured"},
        },
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            # Request lines are emitted by RequestContextMiddleware instead.
            "django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            "django.channels.server": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
        },
    }
