from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import BooleanField, Case, Q, QuerySet, Value, When

from taxonomy.models import Skill

SUGGESTION_LIMIT = 20
# Low enough to catch a transposition in a short name ("pyhton" vs "Python" scores 0.27).
_MIN_SIMILARITY = 0.25


def suggest_skills(query: str) -> QuerySet[Skill]:
    """Autocomplete: prefix matches first, then substring and close misspellings."""
    query = query.strip()
    if not query:
        return Skill.objects.order_by("name")[:SUGGESTION_LIMIT]
    return (
        Skill.objects.annotate(
            similarity=TrigramSimilarity("name", query),
            is_prefix=Case(
                When(name__istartswith=query, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )
        .filter(Q(name__icontains=query) | Q(similarity__gte=_MIN_SIMILARITY))
        .order_by("-is_prefix", "-similarity", "name")[:SUGGESTION_LIMIT]
    )
