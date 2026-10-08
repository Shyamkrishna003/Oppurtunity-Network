import re
from typing import Any

from rest_framework import serializers

from taxonomy.models import Skill, normalize_skill_name

_SKILL_NAME = re.compile(r"^[\w .+#/&-]+$")


class SkillSerializer(serializers.ModelSerializer[Skill]):
    class Meta:
        model = Skill
        fields = ("id", "name", "slug")


class SkillCreateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(min_length=1, max_length=60)

    def validate_name(self, value: str) -> str:
        name = normalize_skill_name(value)
        if not _SKILL_NAME.match(name) or not any(char.isalnum() for char in name):
            raise serializers.ValidationError(
                "Use letters, digits, spaces and the symbols . + # / & - only."
            )
        return name
