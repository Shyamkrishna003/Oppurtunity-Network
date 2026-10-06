from config.logging import build_logging

from .base import *  # noqa: F403

DEBUG = True

LOGGING = build_logging(json_logs=False, level="INFO")
