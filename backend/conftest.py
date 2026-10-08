from collections.abc import Callable

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from users import tokens
from users.models import User

# What a browser sends from the app itself; the cookie-authenticated endpoints require it.
SAME_ORIGIN = {"Origin": "http://testserver", "X-Requested-With": "fetch"}


@pytest.fixture(autouse=True)
def _isolated_state(settings, tmp_path):
    """Throttle counters and uploaded files must not leak between tests."""
    cache.clear()
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def api_as() -> Callable[[User], APIClient]:
    """Return a client authenticated as the given user."""

    def make(user: User) -> APIClient:
        client = APIClient()
        token, _ = tokens.make_access_token(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    return make
