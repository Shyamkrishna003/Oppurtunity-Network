import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from audit.models import AuditLog
from opportunities import services, tasks
from opportunities.models import Opportunity
from opportunities.tests.factories import make_job

pytestmark = pytest.mark.django_db


def past(**delta):
    return timezone.now() - timedelta(**(delta or {"hours": 1}))


def future():
    return timezone.now() + timedelta(days=3)


def test_the_sweep_expires_only_published_jobs_past_their_deadline():
    due = [make_job(status="PUBLISHED", deadline=past()) for _ in range(2)]
    untouched = [
        make_job(status="PUBLISHED", deadline=future()),
        make_job(status="PUBLISHED", deadline=None),
        make_job(status="DRAFT", deadline=past()),
        make_job(status="CLOSED", deadline=past()),
        make_job(status="ARCHIVED", deadline=past()),
    ]
    before = {job.pk: job.status for job in untouched}

    assert tasks.expire_due() == 2

    for job in due:
        job.refresh_from_db()
        assert (job.status, job.close_reason) == ("EXPIRED", "")
        assert job.closed_at is not None
    assert {job.pk: Opportunity.objects.get(pk=job.pk).status for job in untouched} == before
    logs = AuditLog.objects.filter(action="opportunity.expired")
    assert {log.target_id for log in logs} == {job.pk for job in due}
    assert all(log.actor is None and log.actor_type == "SYSTEM" for log in logs)


def test_running_the_sweep_again_does_nothing():
    make_job(status="PUBLISHED", deadline=past())

    assert (services.expire_due(), services.expire_due()) == (1, 0)
    assert AuditLog.objects.filter(action="opportunity.expired").count() == 1


def test_the_sweep_works_through_a_backlog_in_batches(monkeypatch):
    monkeypatch.setattr(services, "EXPIRY_BATCH", 2)
    for hours in (3, 2, 1):
        make_job(status="PUBLISHED", deadline=past(hours=hours))

    assert [services.expire_due() for _ in range(3)] == [2, 1, 0]


def test_an_expired_job_stays_visible_and_cannot_be_edited_or_republished(api, api_as):
    job = make_job(status="PUBLISHED", deadline=past())
    services.expire_due()
    url = f"/api/v1/opportunities/{job.pk}/"
    client = api_as(job.creator)

    assert api.get(url).json()["status"] == "EXPIRED"
    assert client.patch(url, {"description": "Too late."}).status_code == 409
    assert client.post(f"{url}publish/").status_code == 409
    assert client.post(f"{url}close/", {"reason": "OTHER"}).status_code == 409
    assert client.post(f"{url}archive/").json()["status"] == "ARCHIVED"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_closing_and_expiring_at_the_same_moment_settles_on_one_outcome():
    """A manager closes a job just as the sweep reaches it. Exactly one of the two wins, and
    the audit trail records only the one that happened."""
    job = make_job(status="PUBLISHED", deadline=past())
    barrier = threading.Barrier(2)
    failures = []

    def run(call):
        barrier.wait()
        try:
            call()
        except Exception as exc:
            failures.append(exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(services.expire_due,)),
        threading.Thread(
            target=run,
            args=(
                lambda: services.close(actor=job.creator, opportunity_id=job.pk, reason="FILLED"),
            ),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    job.refresh_from_db()
    outcomes = set(
        AuditLog.objects.filter(
            target_id=job.pk, action__in=["opportunity.closed", "opportunity.expired"]
        ).values_list("action", flat=True)
    )
    assert job.status in ("CLOSED", "EXPIRED")
    assert outcomes == {f"opportunity.{job.status.lower()}"}
    # Losing the race to the sweep is reported to the manager as a conflict, not swallowed.
    assert len(failures) == (1 if job.status == "EXPIRED" else 0)
