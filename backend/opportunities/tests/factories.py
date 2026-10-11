from datetime import timedelta

from django.utils import timezone

from jobs.models import JobDetail
from opportunities import search
from opportunities.models import Opportunity, OpportunityCommunity
from taxonomy.models import Skill
from users.tests.factories import UserFactory

_counter = iter(range(1, 1_000_000))

# A request body that is complete enough to publish.
COMPLETE_JOB = {
    "employment_type": "FULL_TIME",
    "experience_level": "MID",
}


def make_job(*, status="DRAFT", skills=("Python",), job=None, **fields) -> Opportunity:
    """A job opportunity in the given state, complete enough to publish unless told otherwise.

    Rows are written directly (not through the services), so tests can start from any state.
    """
    now = timezone.now()
    if status != "DRAFT":
        fields.setdefault("published_at", now - timedelta(days=1))
    if status in ("CLOSED", "EXPIRED", "ARCHIVED"):
        fields.setdefault("closed_at", now)
    if status == "CLOSED":
        fields.setdefault("close_reason", "FILLED")
    if "creator" not in fields:
        fields["creator"] = UserFactory()
    fields.setdefault("title", f"Backend Engineer {next(_counter)}")
    fields.setdefault("description", "Build and run our Django services.")
    fields.setdefault("work_mode", "REMOTE")

    opportunity = Opportunity.objects.create(type="JOB", status=status, **fields)
    JobDetail.objects.create(opportunity=opportunity, **{**COMPLETE_JOB, **(job or {})})
    opportunity.skills.set(Skill.objects.filter(name__in=skills))
    search.reindex(opportunity)
    return opportunity


def distribute(opportunity, community, status="APPROVED", **fields) -> OpportunityCommunity:
    return OpportunityCommunity.objects.create(
        opportunity=opportunity, community=community, status=status, **fields
    )
