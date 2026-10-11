from typing import Any

from rest_framework import serializers

from jobs.models import ApplicationMethod, JobDetail


class JobDetailSerializer(serializers.ModelSerializer[JobDetail]):
    """The ``job`` object nested in an opportunity, for reading and writing."""

    class Meta:
        model = JobDetail
        fields = (
            "department",
            "employment_type",
            "experience_level",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "application_method",
            "external_url",
            "openings",
        )

    def validate_salary_currency(self, value: str) -> str:
        if value and not (len(value) == 3 and value.isascii() and value.isalpha()):
            raise serializers.ValidationError("Use a three-letter currency code, such as INR.")
        return value.upper()

    def validate_openings(self, value: int) -> int:
        if value < 1:
            raise serializers.ValidationError("There must be at least one opening.")
        return value

    def _existing(self) -> JobDetail | None:
        """The job being edited. When nested in an opportunity update, DRF does not hand the
        nested serializer its instance, so it is taken from the parent's."""
        if self.instance is not None:
            return self.instance
        parent = self.parent
        opportunity = getattr(parent, "instance", None) if parent is not None else None
        return getattr(opportunity, "job", None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        existing = self._existing()

        def value(field: str) -> Any:
            return attrs[field] if field in attrs else getattr(existing, field, None)

        low, high = value("salary_min"), value("salary_max")
        if low is not None and high is not None and low > high:
            raise serializers.ValidationError(
                {"salary_max": "The maximum must not be below the minimum."}
            )

        if value("application_method") == ApplicationMethod.EXTERNAL:
            if not value("external_url"):
                raise serializers.ValidationError(
                    {"external_url": "Give the address where people apply."}
                )
        elif value("external_url"):
            # Applications are taken here, so a stale outside link must not linger.
            attrs["external_url"] = ""
        return attrs
