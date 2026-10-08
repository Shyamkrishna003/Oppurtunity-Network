from django.db import IntegrityError, transaction

from common.errors import BusinessRuleViolation
from taxonomy.models import Skill, skill_slug
from users.models import User


def get_or_create_skill(*, name: str, created_by: User) -> tuple[Skill, bool]:
    """Return the skill with this name (case-insensitive), creating it if needed."""
    slug = skill_slug(name)
    if not slug:
        raise BusinessRuleViolation(
            "This is not a usable skill name.",
            code="invalid_skill_name",
            errors={"name": ["This is not a usable skill name."]},
        )

    def find() -> Skill | None:
        # Either match means "the same skill": "node.js" vs "Node.js", or "Node JS" vs "Node.js".
        return (
            Skill.objects.filter(name__iexact=name).first()
            or Skill.objects.filter(slug=slug).first()
        )

    existing = find()
    if existing is not None:
        return existing, False
    try:
        with transaction.atomic():
            return Skill.objects.create(name=name, slug=slug, created_by=created_by), True
    except IntegrityError:
        # A concurrent request created it first.
        existing = find()
        if existing is None:
            raise
        return existing, False
