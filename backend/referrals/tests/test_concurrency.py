"""Races that the locks and constraints must settle. Real threads, real transactions."""

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from applications import services as applications
from applications.tests.factories import pdf
from common.errors import Conflict
from communities.tests.test_concurrency import errors, run_together
from referrals import services
from referrals.models import ReferralRequest, ReferralStatusHistory
from referrals.tests.factories import colleague, make_referral, referral_setup

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)

NOTE = "I worked with Rita for two years and would hire her again."


def test_requests_sent_at_once_cannot_pass_the_limit_or_duplicate():
    job, people = referral_setup()
    requester = people["requester"]
    referrers = [people["referrer"], *(colleague(job, requester) for _ in range(4))]

    def ask(referrer):
        return lambda: services.request(
            user=requester, opportunity_id=job.pk, referrer_id=referrer.pk, message=""
        )

    # Five different people at once, and the first of them twice.
    outcomes = run_together(*[ask(referrer) for referrer in referrers], ask(referrers[0]))

    refused = errors(outcomes)
    assert all(isinstance(error, Conflict) for error in refused)
    assert ReferralRequest.objects.filter(requester=requester).count() == 3
    assert len(refused) == 3
    assert ReferralRequest.objects.values("referrer").distinct().count() == 3


def test_accepting_while_the_request_is_cancelled_has_one_winner():
    job, people = referral_setup()
    referral = make_referral(job, people["requester"], people["referrer"])

    outcomes = run_together(
        lambda: services.accept(user=people["referrer"], referral_id=referral.pk),
        lambda: services.cancel(user=people["requester"], referral_id=referral.pk),
    )

    assert len(errors(outcomes)) == 1
    referral.refresh_from_db()
    assert referral.status in ("ACCEPTED", "CANCELLED")
    assert ReferralStatusHistory.objects.filter(referral=referral).count() == 2


def test_applying_while_the_referral_is_being_made_still_links_the_two():
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    referral = make_referral(job, requester, referrer, "ACCEPTED")

    outcomes = run_together(
        lambda: services.refer(user=referrer, referral_id=referral.pk, endorsement_note=NOTE),
        lambda: applications.apply(
            applicant=requester, opportunity_id=job.pk, resume=pdf(), cover_note=""
        ),
    )

    # Whichever went first, the referral ends up following the application.
    assert errors(outcomes) == []
    referral.refresh_from_db()
    assert referral.status == "APPLICATION_SUBMITTED"
    assert referral.application is not None
    assert referral.application.applicant == requester


def test_the_database_itself_refuses_a_duplicate_a_self_referral_and_an_unknown_status():
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    referral = make_referral(job, requester, referrer, "DECLINED")
    now = timezone.now()

    def create(**fields):
        return ReferralRequest.objects.create(
            opportunity=job, expires_at=now, status_changed_at=now, **fields
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        create(requester=requester, referrer=referrer)
    with pytest.raises(IntegrityError), transaction.atomic():
        create(requester=requester, referrer=requester)
    with pytest.raises(IntegrityError), transaction.atomic():
        ReferralRequest.objects.filter(pk=referral.pk).update(status="MAYBE")
    with pytest.raises(IntegrityError), transaction.atomic():
        ReferralStatusHistory.objects.create(referral=referral, to_status="MAYBE")
