from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string


def send_templated(*, to: str, subject: str, template: str, context: dict[str, Any]) -> None:
    """Send a plain-text email rendered from ``template``. Call from a Celery task."""
    body = render_to_string(template, {"frontend_url": settings.FRONTEND_URL, **context})
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to])
