import re

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Lower
from django.utils.text import slugify

from common.models import UUIDModel

# Symbols that carry meaning in skill names and would otherwise be dropped by slugify,
# making "C", "C++" and "C#" collide.
_SLUG_SYMBOLS = {"+": " plus ", "#": " sharp ", ".": " dot ", "&": " and ", "/": " "}
_WHITESPACE = re.compile(r"\s+")


def normalize_skill_name(name: str) -> str:
    return _WHITESPACE.sub(" ", name).strip()


def skill_slug(name: str) -> str:
    for symbol, word in _SLUG_SYMBOLS.items():
        name = name.replace(symbol, word)
    return slugify(name)


class Skill(UUIDModel):
    """Shared taxonomy entry: matched against profiles (has / interested in) and opportunities."""

    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=80, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("name"), name="taxonomy_skill_name_ci_unique"),
        ]
        indexes = [
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="taxonomy_skill_name_trgm"),
        ]

    def __str__(self) -> str:
        return self.name
