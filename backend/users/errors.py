from rest_framework import status

from common.errors import DomainError


class InvalidCredentials(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Incorrect email or password."
    default_code = "invalid_credentials"


class AccountSuspended(DomainError):
    """The account exists and the credentials were right, but a moderator has suspended it."""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "This account has been suspended. Check your email for the reason."
    default_code = "account_suspended"


class PostingRestricted(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "A moderator has restricted this account from posting for now."
    default_code = "posting_restricted"


class SessionExpired(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Your session has ended. Sign in again."
    default_code = "session_expired"
