from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.request import Request

from users import tokens
from users.models import User


class AccessTokenAuthentication(BaseAuthentication):
    """``Authorization: Bearer <access token>``. The user is re-read on every request,
    so deactivating an account takes effect immediately."""

    keyword = b"bearer"

    def authenticate(self, request: Request) -> tuple[User, None] | None:
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Malformed authorization header.")
        try:
            user_id = tokens.read_access_token(parts[1].decode("ascii", errors="replace"))
        except tokens.InvalidToken as exc:
            raise exceptions.AuthenticationFailed("Invalid or expired access token.") from exc

        user = User.objects.select_related("profile").filter(pk=user_id, is_active=True).first()
        if user is None:
            raise exceptions.AuthenticationFailed("Invalid or expired access token.")
        return user, None

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
