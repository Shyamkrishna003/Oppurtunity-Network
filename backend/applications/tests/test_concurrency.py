"""Races that the locks and constraints must settle. Real threads, real transactions."""

from pathlib import Path

import pytest
from django.db import IntegrityError, transaction

from applications import services
from applications.models import Application, ApplicationStatusHistory
from applications.tests.factories import make_application, pdf
from audit.models import AuditLog
from communities.tests.test_concurrency import errors, run_together
from notifications.models import Notification
from opportunities.tests.factories import make_job
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)


def test_applying_twice_at_once_leaves_one_application_and_one_file(settings):
    job = make_job(status="PUBLISHED")
    applicant = UserFactory()

    def apply():
        return services.apply(
            applicant=applicant, opportunity_id=job.pk, resume=pdf(), cover_note=""
        )

    outcomes = run_together(*[apply] * 4)

    assert errors(outcomes) == []
    assert sorted(created for _, created in outcomes) == [False, False, False, True]
    assert len({application.pk for application, _ in outcomes}) == 1
    assert Application.objects.count() == 1
    assert ApplicationStatusHistory.objects.count() == 1
    assert AuditLog.objects.filter(action="application.submitted").count() == 1
    assert Notification.objects.count() == 1
    # The uploads that lost the race were cleaned up.
    files = [p for p in Path(settings.PRIVATE_MEDIA_ROOT).rglob("*") if p.is_file()]
    assert len(files) == 1


def test_withdrawing_twice_at_once_happens_once():
    application = make_application(status="SCREENING")

    def withdraw():
        return services.withdraw(user=application.applicant, application_id=application.pk)

    outcomes = run_together(withdraw, withdraw)

    assert errors(outcomes) == []
    assert ApplicationStatusHistory.objects.filter(to_status="WITHDRAWN").count() == 1
    assert AuditLog.objects.filter(action="application.withdrawn").count() == 1


def test_the_database_itself_refuses_a_second_application_and_an_unknown_status():
    application = make_application()

    with pytest.raises(IntegrityError), transaction.atomic():
        Application.objects.create(
            opportunity=application.opportunity,
            applicant=application.applicant,
            resume="resumes/other.pdf",
            status_changed_at=application.status_changed_at,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Application.objects.filter(pk=application.pk).update(status="MAYBE")
    with pytest.raises(IntegrityError), transaction.atomic():
        ApplicationStatusHistory.objects.create(application=application, to_status="MAYBE")
