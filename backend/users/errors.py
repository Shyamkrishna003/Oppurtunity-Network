from rest_framework import status

from common.errors import DomainError


class InvalidCredentials(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Incorrect email or password."
    default_code = "invalid_credentials"


class SessionExpired(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Your session has ended. Sign in again."
    default_code = "session_expired"
