from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import BusinessRuleViolation, Conflict
from common.throttles import ScopedThrottle
from referrals import selectors, services
from referrals.api import serializers
from referrals.models import ReferralRequest, ReferralStatus
from referrals.policies import BARRIER_MESSAGES, MAX_OPEN_PER_JOB, Barrier
from users.api.utils import current_user
from users.permissions import IsVerified

ROLES = ("requester", "referrer")


def _detail(request: Request, referral_id: UUID, status_code: int = 200) -> Response:
    """The referral as the caller now sees it, including what they may do with it."""
    user = current_user(request)
    referral = selectors.get_referral(user, referral_id)
    context = {"actor": selectors.actor_for(user, referral)}
    data = serializers.ReferralDetailSerializer(referral, context=context).data
    return Response(data, status=status_code)


class EligibleReferrersView(APIView):
    permission_classes = [IsVerified]

    @extend_schema(responses=serializers.EligibleReferrersSerializer)
    def get(self, request: Request, opportunity_id: UUID) -> Response:
        """Which of the caller's own connections they could ask to refer them for this job.

        Only ever the caller's connections, only those who show their membership of the
        organization publicly and take referral requests, and never anyone already asked.
        409 ``not_accepting`` or 422 if referrals cannot be asked for here at all.
        """
        user = current_user(request)
        opportunity = selectors.get_job(user, opportunity_id)
        barrier = selectors.barrier_to_requesting(user, opportunity)
        if barrier is not None:
            error = Conflict if barrier is Barrier.NOT_ACCEPTING else BusinessRuleViolation
            raise error(BARRIER_MESSAGES[barrier], code=barrier.value)
        payload = {
            "referrers": selectors.eligible_referrers(user, opportunity),
            "remaining": max(MAX_OPEN_PER_JOB - selectors.open_count(user, opportunity), 0),
        }
        return Response(serializers.EligibleReferrersSerializer(payload).data)


class ReferralRequestCreateView(APIView):
    permission_classes = [IsVerified]
    throttle_classes = [ScopedThrottle]
    throttle_scope = "referral_request"

    @extend_schema(
        request=serializers.ReferralRequestCreateSerializer,
        responses={201: serializers.ReferralDetailSerializer},
    )
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Ask one of your connections to refer you for this job.

        422 ``not_eligible`` whenever that person cannot be asked, whatever the reason.
        409 ``already_requested`` (one request per person and job, ever) or
        ``too_many_requests`` (three open at a time for one job).
        """
        serializer = serializers.ReferralRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        referral = services.request(
            user=current_user(request),
            opportunity_id=opportunity_id,
            referrer_id=serializer.validated_data["referrer_id"],
            message=serializer.validated_data["message"],
        )
        return _detail(request, referral.pk, status.HTTP_201_CREATED)


class ReferralListView(generics.ListAPIView[ReferralRequest]):
    """The caller's referrals: those they asked for (the default) or those asked of them."""

    serializer_class = serializers.ReferralSerializer

    def get_queryset(self) -> QuerySet[ReferralRequest]:
        if getattr(self, "swagger_fake_view", False):
            return ReferralRequest.objects.none()
        params = self.request.query_params
        role = params.get("role", ROLES[0])
        if role not in ROLES:
            raise ValidationError({"role": [f"Choose one of: {', '.join(ROLES)}."]})
        requested = params.get("status", "")
        if requested and requested not in ReferralStatus.values:
            raise ValidationError(
                {"status": [f"Choose one of: {', '.join(ReferralStatus.values)}."]}
            )
        try:
            opportunity_id = UUID(params["opportunity"]) if "opportunity" in params else None
        except ValueError:
            raise ValidationError({"opportunity": ["Not a valid ID."]}) from None
        return selectors.list_for(
            current_user(self.request),
            as_referrer=role == "referrer",
            status=requested,
            opportunity_id=opportunity_id,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("role", str, enum=ROLES),
            OpenApiParameter("status", str, enum=ReferralStatus.values),
            OpenApiParameter("opportunity", UUID),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class ReferralDetailView(APIView):
    @extend_schema(responses=serializers.ReferralDetailSerializer)
    def get(self, request: Request, referral_id: UUID) -> Response:
        """One referral with its history: for the two people, and for whoever manages the
        job once the referral has been made."""
        return _detail(request, referral_id)


class AcceptView(APIView):
    @extend_schema(request=None, responses=serializers.ReferralDetailSerializer)
    def post(self, request: Request, referral_id: UUID) -> Response:
        """Agree to refer the person who asked. The employer sees nothing yet."""
        services.accept(user=current_user(request), referral_id=referral_id)
        return _detail(request, referral_id)


class DeclineView(APIView):
    @extend_schema(request=None, responses=serializers.ReferralDetailSerializer)
    def post(self, request: Request, referral_id: UUID) -> Response:
        """Decline. No reason is asked for or passed on."""
        services.decline(user=current_user(request), referral_id=referral_id)
        return _detail(request, referral_id)


class CancelView(APIView):
    @extend_schema(request=None, responses=serializers.ReferralDetailSerializer)
    def post(self, request: Request, referral_id: UUID) -> Response:
        """Take back a request that has not been answered yet."""
        services.cancel(user=current_user(request), referral_id=referral_id)
        return _detail(request, referral_id)


class ReferView(APIView):
    @extend_schema(
        request=serializers.ReferSerializer, responses=serializers.ReferralDetailSerializer
    )
    def post(self, request: Request, referral_id: UUID) -> Response:
        """Make the referral, with a note for the people hiring. From here they see it.

        422 ``not_a_member`` if the caller has left the organization; 409 ``not_accepting``
        if the job no longer takes applications.
        """
        serializer = serializers.ReferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.refer(
            user=current_user(request),
            referral_id=referral_id,
            endorsement_note=serializer.validated_data["endorsement_note"],
        )
        return _detail(request, referral_id)


class BackOutView(APIView):
    @extend_schema(request=None, responses=serializers.ReferralDetailSerializer)
    def post(self, request: Request, referral_id: UUID) -> Response:
        """Change your mind after agreeing, before the referral is made."""
        services.back_out(user=current_user(request), referral_id=referral_id)
        return _detail(request, referral_id)
