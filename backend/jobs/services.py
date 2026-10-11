"""The job-specific half of an opportunity. Called by the opportunity service, inside its
transaction; nothing else creates or changes a ``JobDetail``."""

from typing import Any

from common.errors import FieldErrors
from jobs.models import JobDetail
from opportunities.models import Opportunity

# What may still change once the job is published.
EDITABLE_WHEN_PUBLISHED = frozenset({"openings"})


def create_detail(opportunity: Opportunity, values: dict[str, Any]) -> JobDetail:
    return JobDetail.objects.create(opportunity=opportunity, **values)


def update_detail(detail: JobDetail, changes: dict[str, Any]) -> None:
    if not changes:
        return
    for field, value in changes.items():
        setattr(detail, field, value)
    detail.save(update_fields=list(changes))


def publication_errors(detail: JobDetail) -> FieldErrors:
    """What is still missing before this job can be published, keyed like the request body."""
    errors: FieldErrors = {}
    if not detail.employment_type:
        errors["job.employment_type"] = ["Choose the employment type."]
    if not detail.experience_level:
        errors["job.experience_level"] = ["Choose the experience level."]
    has_salary = detail.salary_min is not None or detail.salary_max is not None
    if has_salary and not detail.salary_currency:
        errors["job.salary_currency"] = ["Give the currency of the salary."]
    if has_salary and not detail.salary_period:
        errors["job.salary_period"] = ["Say whether the salary is per year, month or hour."]
    return errors
