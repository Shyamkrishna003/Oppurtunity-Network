from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from applications import selectors, services
from applications.api import serializers
from applications.models import Application, ApplicationStatus
from common.throttles import ScopedThrottle
from users.api.utils import current_user
from users.permissions import IsVerified


def _detail(request: Request, application_id: UUID, status_code: int = 200) -> Response:
    """The application as the caller now sees it, including what they may do with it."""
    user = current_user(request)
    application = selectors.get_application(user, application_id)
    context = {"actor": selectors.actor_for(user, application)}
    data = serializers.ApplicationDetailSerializer(application, context=context).data
    return Response(data, status=status_code)


class ApplyView(APIView):
    permission_classes = [IsVerified]
    parser_classes = [MultiPartParser]
    throttle_classes = [ScopedThrottle]
    throttle_scope = "application_create"

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "required": ["resume"],
                "properties": {
                    "resume": {"type": "string", "format": "binary"},
                    "cover_note": {"type": "string", "maxLength": 4000},
                },
            }
        },
        responses={
            201: serializers.ApplicationDetailSerializer,
            200: serializers.ApplicationDetailSerializer,
        },
    )
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Apply to a job with a PDF resume (5 MB at most) and an optional note.

        Answers 201 for a new application. If the caller already has one for this job, in
        any state, that one is returned with 200 and nothing is changed.
        """
        serializer = serializers.ApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application, created = services.apply(
            applicant=current_user(request),
            opportunity_id=opportunity_id,
            resume=request.FILES.get("resume"),
            cover_note=serializer.validated_data["cover_note"],
        )
        return _detail(
            request, application.pk, status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class MyApplicationsView(generics.ListAPIView[Application]):
    """What the caller has applied to, newest first."""

    serializer_class = serializers.ApplicationSerializer

    def get_queryset(self) -> QuerySet[Application]:
        if getattr(self, "swagger_fake_view", False):
            return Application.objects.none()
        requested = self.request.query_params.get("status", "")
        if requested and requested not in ApplicationStatus.values:
            raise ValidationError(
                {"status": [f"Choose one of: {', '.join(ApplicationStatus.values)}."]}
            )
        return selectors.list_mine(current_user(self.request), requested)

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=ApplicationStatus.values)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class ApplicationDetailView(APIView):
    @extend_schema(responses=serializers.ApplicationDetailSerializer)
    def get(self, request: Request, application_id: UUID) -> Response:
        """One application with its history, for the applicant or whoever manages the job."""
        return _detail(request, application_id)


class WithdrawView(APIView):
    @extend_schema(request=None, responses=serializers.ApplicationDetailSerializer)
    def post(self, request: Request, application_id: UUID) -> Response:
        """Take your application back. It cannot be reinstated or replaced afterwards."""
        services.withdraw(user=current_user(request), application_id=application_id)
        return _detail(request, application_id)


class ResumeView(APIView):
    @extend_schema(responses=serializers.ResumeLinkSerializer)
    def get(self, request: Request, application_id: UUID) -> Response:
        """A link to download the resume, valid for one minute."""
        url = services.resume_link(user=current_user(request), application_id=application_id)
        return Response(
            {"url": url, "expires_in": int(settings.PRIVATE_DOWNLOAD_TTL.total_seconds())}
        )
