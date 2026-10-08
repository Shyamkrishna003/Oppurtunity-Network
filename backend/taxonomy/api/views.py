from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from common.throttles import ScopedThrottle
from taxonomy import selectors, services
from taxonomy.api.serializers import SkillCreateSerializer, SkillSerializer
from users.api.utils import current_user
from users.permissions import IsVerified


class SkillListView(APIView):
    throttle_scope = "skill_create"

    def get_permissions(self) -> list[BasePermission]:
        return [IsVerified()] if self.request.method == "POST" else [IsAuthenticated()]

    def get_throttles(self) -> list[BaseThrottle]:
        return [ScopedThrottle()] if self.request.method == "POST" else []

    @extend_schema(
        parameters=[OpenApiParameter("q", str, description="Text to complete.")],
        responses=SkillSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Up to 20 skills matching ``q``, best match first."""
        skills = selectors.suggest_skills(request.query_params.get("q", "")[:60])
        return Response(SkillSerializer(skills, many=True).data)

    @extend_schema(
        request=SkillCreateSerializer, responses={200: SkillSerializer, 201: SkillSerializer}
    )
    def post(self, request: Request) -> Response:
        """Add a skill to the shared list, or return the existing one with that name."""
        serializer = SkillCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        skill, created = services.get_or_create_skill(
            name=serializer.validated_data["name"], created_by=current_user(request)
        )
        return Response(
            SkillSerializer(skill).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
