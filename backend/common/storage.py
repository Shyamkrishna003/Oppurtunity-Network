"""Private files: uploads that must never be reachable by URL alone (resumes).

They are kept apart from the public media (avatars, logos) and handed out only through a
link that is signed and expires within a minute, created after the caller has passed the
same permission check as the API. Locally that link points at ``download`` below; with an
S3-compatible bucket in production, ``PrivateFileSystemStorage`` is swapped for the bucket
and ``download_url`` for its presigned URLs, and nothing that calls this module changes.
"""

import os
from typing import Any

from django.conf import settings
from django.core import signing
from django.core.files.storage import FileSystemStorage, Storage
from django.http import FileResponse, Http404
from django.urls import reverse
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request

_SALT = "common.storage.download"


class PrivateFileSystemStorage(FileSystemStorage):
    """A directory outside ``MEDIA_ROOT``, so that no web server location ever serves it."""

    # Read on every use, not cached, so the directory follows the setting (tests move it).
    @property
    def base_location(self) -> str:
        return str(settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self) -> str:
        return os.path.abspath(self.base_location)

    def url(self, name: str | None) -> str:
        raise ValueError("Private files have no public address; use download_url().")


_storage = PrivateFileSystemStorage()


def private_storage() -> Storage:
    return _storage


def download_url(name: str, *, filename: str, content_type: str) -> str:
    """A link to one private file that works for ``PRIVATE_DOWNLOAD_TTL``.

    The caller has already decided that the person asking may have the file. ``filename`` is
    what the browser saves it as; it is chosen by the server, never taken from the upload.
    """
    token = signing.dumps({"n": name, "f": filename, "t": content_type}, salt=_SALT)
    return reverse("private-download", kwargs={"token": token})


@extend_schema(exclude=True)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def download(request: Request, token: str) -> FileResponse:
    """Serve the file a signed link refers to. The signature is the authorization: browsers
    cannot attach our access token to a plain download."""
    try:
        claim: dict[str, Any] = signing.loads(
            token, salt=_SALT, max_age=settings.PRIVATE_DOWNLOAD_TTL
        )
        file = _storage.open(claim["n"], "rb")
    except (signing.BadSignature, FileNotFoundError, KeyError) as exc:
        # Forged, expired, or pointing at a file since deleted: all the same from outside.
        raise Http404 from exc

    response = FileResponse(file, as_attachment=True, filename=claim["f"], content_type=claim["t"])
    response["Cache-Control"] = "private, no-store"
    # Uploaded content is never rendered inside our origin, even if a browser is asked to.
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["X-Content-Type-Options"] = "nosniff"
    return response
