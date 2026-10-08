from rest_framework.request import Request

from users.models import User


def current_user(request: Request) -> User:
    """The authenticated user, typed. Only call from views that require authentication."""
    user = request.user
    assert isinstance(user, User)
    return user
