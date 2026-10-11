"""Keeps an opportunity's search columns in step with the text they are built from."""

from django.contrib.postgres.search import SearchVector
from django.db.models import Value

from opportunities.models import Opportunity

_CONFIG = "english"


def reindex(opportunity: Opportunity) -> None:
    """Rebuild ``skills_text`` and ``search_vector``. Call inside the transaction that changed
    the title, description, location, skills, or the organization's name.

    Weights decide ranking: a match in the title (A) outranks one in the skills or
    organization name (B), then location (C), then the description (D).
    """
    skills_text = " ".join(opportunity.skills.order_by("name").values_list("name", flat=True))
    organization = opportunity.organization.name if opportunity.organization else ""
    location = " ".join(filter(None, [opportunity.city, opportunity.region]))

    def vector(text: str, weight: str) -> SearchVector:
        return SearchVector(Value(text), weight=weight, config=_CONFIG)

    Opportunity.objects.filter(pk=opportunity.pk).update(
        skills_text=skills_text,
        search_vector=(
            vector(opportunity.title, "A")
            + vector(f"{skills_text} {organization}", "B")
            + vector(location, "C")
            + vector(opportunity.description, "D")
        ),
    )
    opportunity.skills_text = skills_text
