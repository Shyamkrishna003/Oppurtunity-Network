from django.conf import settings
from django.db import models

from common.models import TimestampedModel, UUIDModel


class ReferralStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Requested"
    ACCEPTED = "ACCEPTED", "Accepted"
    DECLINED = "DECLINED", "Declined"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"
    REFERRED = "REFERRED", "Referred"
    APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED", "Application submitted"
    INTERVIEW = "INTERVIEW", "Interview"
    OFFER = "OFFER", "Offer"
    JOINED = "JOINED", "Joined"
    CLOSED = "CLOSED", "Closed"


class ReferralRequest(TimestampedModel):
    """One person asking one of their connections to refer them for one job.

    A referral is a workflow on an organization's job, not an opportunity of its own. There
    is at most one per job, requester and referrer, ever: a declined, cancelled or expired
    request is kept as the record and cannot be sent again.

    Up to ``REFERRED`` the two people move it. After that ``status`` only mirrors the
    requester's application to the job and is written by the application service alone, so
    the two can never disagree.
    """

    opportunity = models.ForeignKey(
        "opportunities.Opportunity", on_delete=models.PROTECT, related_name="referral_requests"
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="referrals_requested"
    )
    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="referrals_received"
    )
    # From the requester to the referrer. Nobody else reads it.
    message = models.TextField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=21, choices=ReferralStatus.choices, default=ReferralStatus.REQUESTED
    )
    # From the referrer to the people hiring. The requester does not read it.
    endorsement_note = models.TextField(max_length=2000, blank=True)
    # Set when the referral is made. From then on the job's managers can see it.
    referred_at = models.DateTimeField(null=True, blank=True)
    # The requester's application to the job, once there is one and the referral was made.
    application = models.ForeignKey(
        "applications.Application",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="referrals",
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    # When an unanswered request lapses.
    expires_at = models.DateTimeField()
    status_changed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "requester", "referrer"], name="referrals_one_per_referrer"
            ),
            models.CheckConstraint(
                condition=~models.Q(requester=models.F("referrer")), name="referrals_not_self"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ReferralStatus.values),
                name="referrals_status_valid",
            ),
        ]
        indexes = [
            # "Asked of me" and "asked by me", newest first, optionally one status.
            models.Index(fields=["referrer", "status", "created_at"], name="referrals_received"),
            models.Index(fields=["requester", "status", "created_at"], name="referrals_sent"),
            # A job's referrals, and the sweep that closes those of jobs no longer open.
            models.Index(fields=["opportunity", "status"], name="referrals_for_job"),
            # The expiry sweep: unanswered requests, soonest first.
            models.Index(
                fields=["expires_at"],
                condition=models.Q(status=ReferralStatus.REQUESTED),
                name="referrals_unanswered",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.requester_id} via {self.referrer_id} for {self.opportunity_id}"


class ReferralStatusHistory(UUIDModel):
    """Append-only: one row per move, including the first (from nothing to REQUESTED)."""

    referral = models.ForeignKey(ReferralRequest, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=21, choices=ReferralStatus.choices, blank=True)
    to_status = models.CharField(max_length=21, choices=ReferralStatus.choices)
    # NULL for a change made by the system: expiry, and everything that follows an application.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "referral status histories"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(from_status__in=["", *ReferralStatus.values])
                & models.Q(to_status__in=ReferralStatus.values),
                name="referrals_history_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["referral", "created_at"], name="referrals_history"),
        ]

    def __str__(self) -> str:
        return f"{self.referral_id}: {self.from_status or 'new'} -> {self.to_status}"
