from django.conf import settings
from django.db import models

from common.models import TimestampedModel, UUIDModel


class ApplicationStatus(models.TextChoices):
    APPLIED = "APPLIED", "Applied"
    SCREENING = "SCREENING", "Screening"
    SHORTLISTED = "SHORTLISTED", "Shortlisted"
    INTERVIEW = "INTERVIEW", "Interview"
    OFFER = "OFFER", "Offer"
    HIRED = "HIRED", "Hired"
    REJECTED = "REJECTED", "Not selected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class Application(TimestampedModel):
    """One person's application to one job.

    There is at most one per person and job, ever: a withdrawn or rejected application is
    kept as the record and is not replaced by a new one. ``status`` only moves through
    ``policies.PIPELINE``, and every move adds an ``ApplicationStatusHistory`` row.
    """

    opportunity = models.ForeignKey(
        "opportunities.Opportunity", on_delete=models.PROTECT, related_name="applications"
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="applications"
    )
    status = models.CharField(
        max_length=12, choices=ApplicationStatus.choices, default=ApplicationStatus.APPLIED
    )
    # Key of the PDF in private storage: random, never derived from the uploaded filename.
    resume = models.CharField(max_length=255)
    cover_note = models.TextField(max_length=4000, blank=True)
    # The applicant's headline as it was when they applied; their profile may change later.
    headline = models.CharField(max_length=140, blank=True)
    status_changed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "applicant"], name="applications_one_per_job"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ApplicationStatus.values),
                name="applications_status_valid",
            ),
        ]
        indexes = [
            # A job's pipeline, one stage at a time, oldest first.
            models.Index(
                fields=["opportunity", "status", "created_at"], name="applications_pipeline"
            ),
            # "My applications", newest first.
            models.Index(fields=["applicant", "-created_at"], name="applications_mine"),
        ]

    def __str__(self) -> str:
        return f"{self.applicant_id} -> {self.opportunity_id} ({self.status})"


class ApplicationStatusHistory(UUIDModel):
    """Append-only: one row per move, including the first (from nothing to APPLIED)."""

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=12, choices=ApplicationStatus.choices, blank=True)
    to_status = models.CharField(max_length=12, choices=ApplicationStatus.choices)
    # NULL for a change made by the system.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Written by whoever manages the job, for the others who do. Never shown to the applicant.
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "application status histories"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(from_status__in=["", *ApplicationStatus.values])
                & models.Q(to_status__in=ApplicationStatus.values),
                name="applications_history_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["application", "created_at"], name="applications_history"),
        ]

    def __str__(self) -> str:
        return f"{self.application_id}: {self.from_status or 'new'} -> {self.to_status}"
