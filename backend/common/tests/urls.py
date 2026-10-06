"""URLconf with views that raise each kind of error, for testing the error envelope."""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.urls import include, path
from rest_framework import exceptions, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from common.errors import BusinessRuleViolation, InvalidTransition


class _ItemSerializer(serializers.Serializer):
    name = serializers.CharField()


class _OrderSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=5)
    items = _ItemSerializer(many=True)


def _raising(exc_factory):
    @api_view(["GET"])
    @permission_classes([AllowAny])
    def view(request):
        raise exc_factory()

    return view


@api_view(["POST"])
@permission_classes([AllowAny])
def validate(request):
    _OrderSerializer(data=request.data).is_valid(raise_exception=True)
    return Response({})


@api_view(["GET"])
def protected(request):
    return Response({})


urlpatterns = [
    path("validate/", validate),
    path("protected/", protected),
    path("http404/", _raising(Http404)),
    path("django-denied/", _raising(DjangoPermissionDenied)),
    path("throttled/", _raising(lambda: exceptions.Throttled(wait=12.2))),
    path("transition/", _raising(InvalidTransition)),
    path(
        "rule/",
        _raising(
            lambda: BusinessRuleViolation(
                "Deadline has passed.", code="deadline_passed", errors={"deadline": ["Too late."]}
            )
        ),
    ),
    path("boom/", _raising(lambda: RuntimeError("secret internals"))),
    path("", include("config.urls")),
]
