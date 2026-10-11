from django.db import models

from common.choices import ExperienceLevel


class EmploymentType(models.TextChoices):
    FULL_TIME = "FULL_TIME", "Full-time"
    PART_TIME = "PART_TIME", "Part-time"
    CONTRACT = "CONTRACT", "Contract"
    INTERNSHIP = "INTERNSHIP", "Internship"
    TEMPORARY = "TEMPORARY", "Temporary"


class SalaryPeriod(models.TextChoices):
    YEAR = "YEAR", "Per year"
    MONTH = "MONTH", "Per month"
    HOUR = "HOUR", "Per hour"


class ApplicationMethod(models.TextChoices):
    INTERNAL = "INTERNAL", "Apply on Opportunity Network"
    EXTERNAL = "EXTERNAL", "Apply on another website"


class JobDetail(models.Model):
    """The fields only a job has. Exists exactly when ``opportunity.type`` is JOB; both rows
    are created together by the opportunity service."""

    opportunity = models.OneToOneField(
        "opportunities.Opportunity",
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="job",
    )
    department = models.CharField(max_length=80, blank=True)
    # Blank while drafting; required to publish.
    employment_type = models.CharField(max_length=10, choices=EmploymentType.choices, blank=True)
    experience_level = models.CharField(max_length=8, choices=ExperienceLevel.choices, blank=True)
    # Whole units of the currency; salary is optional, but a range needs its currency and period.
    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    salary_currency = models.CharField(max_length=3, blank=True)
    salary_period = models.CharField(max_length=5, choices=SalaryPeriod.choices, blank=True)
    application_method = models.CharField(
        max_length=8, choices=ApplicationMethod.choices, default=ApplicationMethod.INTERNAL
    )
    external_url = models.URLField(blank=True)
    openings = models.PositiveSmallIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(employment_type__in=["", *EmploymentType.values]),
                name="jobs_employment_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(experience_level__in=["", *ExperienceLevel.values]),
                name="jobs_experience_level_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(salary_period__in=["", *SalaryPeriod.values]),
                name="jobs_salary_period_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(salary_min__isnull=True)
                | models.Q(salary_max__isnull=True)
                | models.Q(salary_min__lte=models.F("salary_max")),
                name="jobs_salary_range_ordered",
            ),
            # An external job has a link to apply at; an internal one never does.
            models.CheckConstraint(
                condition=models.Q(application_method=ApplicationMethod.INTERNAL, external_url="")
                | (
                    models.Q(application_method=ApplicationMethod.EXTERNAL)
                    & ~models.Q(external_url="")
                ),
                name="jobs_external_url_matches_method",
            ),
            models.CheckConstraint(
                condition=models.Q(openings__gte=1), name="jobs_openings_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["experience_level"], name="jobs_experience_level"),
            models.Index(fields=["employment_type"], name="jobs_employment_type"),
        ]

    def __str__(self) -> str:
        return f"job {self.pk}"
