"""The rules, without a database: the pipeline and who may apply."""

from datetime import timedelta
from itertools import product

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from applications import policies
from applications.models import Application, ApplicationStatus
from applications.policies import OPEN, PIPELINE, STAGES, Actor, Barrier
from common.errors import InvalidTransition, StaleState
from jobs.models import JobDetail
from opportunities.models import Opportunity

S = ApplicationStatus
MANAGER = Actor(is_applicant=False, is_manager=True)
APPLICANT = Actor(is_applicant=True, is_manager=False)
STRANGER = Actor(is_applicant=False, is_manager=False)


def _expected(source: str, target: str) -> Actor | None:
    """Who may make this move, by the rules as written in the plan; None if nobody."""
    if source not in OPEN:
        return None
    if target == S.WITHDRAWN:
        return APPLICANT
    if target == S.REJECTED:
        return MANAGER
    if target in STAGES and STAGES.index(target) > STAGES.index(S(source)):
        return MANAGER
    return None


EVERY_PAIR = [(a, b) for a, b in product(S.values, S.values) if a != b]


@pytest.mark.parametrize(("source", "target"), EVERY_PAIR)
def test_every_move_is_allowed_to_exactly_the_right_person_or_to_nobody(source, target):
    allowed = _expected(source, target)

    for actor in (MANAGER, APPLICANT, STRANGER, None):
        application = Application(status=source)
        if allowed is None:
            with pytest.raises(InvalidTransition):
                PIPELINE.apply(application, target, actor=actor)
        elif actor == allowed:
            assert PIPELINE.apply(application, target, actor=actor) is True
            assert application.status == target
        else:
            with pytest.raises(PermissionDenied):
                PIPELINE.apply(application, target, actor=actor)
        if actor != allowed:
            assert application.status == source


def test_the_shape_of_the_pipeline():
    assert {s for s in S.values if PIPELINE.is_terminal(s)} == {"HIRED", "REJECTED", "WITHDRAWN"}
    assert set(S.values) - {"HIRED", "REJECTED", "WITHDRAWN"} == OPEN
    # Forward only, and stages may be skipped.
    assert PIPELINE.targets("APPLIED") == set(S.values) - {"APPLIED"}
    assert PIPELINE.targets("OFFER") == {"HIRED", "REJECTED", "WITHDRAWN"}


def test_repeating_a_move_is_a_no_op_and_a_stale_view_is_refused():
    application = Application(status=S.INTERVIEW)

    assert PIPELINE.apply(application, S.INTERVIEW, actor=MANAGER) is False
    with pytest.raises(StaleState):
        PIPELINE.apply(application, S.OFFER, actor=MANAGER, expected=S.SCREENING)


@pytest.mark.parametrize("status", S.values)
def test_what_each_person_may_do_with_an_application(status):
    application = Application(status=status)
    both = Actor(is_applicant=True, is_manager=True)

    assert policies.can_view(APPLICANT) and policies.can_view(MANAGER)
    assert not policies.can_view(STRANGER)
    assert policies.can_withdraw(APPLICANT, application) is (status in OPEN)
    assert not policies.can_withdraw(MANAGER, application)
    assert policies.can_withdraw(both, application) is (status in OPEN)
    # The applicant can always get their own resume back; a withdrawal takes it away from
    # the employer.
    assert policies.can_download_resume(APPLICANT, application)
    assert policies.can_download_resume(MANAGER, application) is (status != "WITHDRAWN")
    assert not policies.can_download_resume(STRANGER, application)


def job(method="INTERNAL", **fields) -> Opportunity:
    opportunity = Opportunity(type="JOB", **{"status": "PUBLISHED", **fields})
    opportunity.job = JobDetail(application_method=method)
    return opportunity


def barrier(opportunity, *, is_manager=False, is_blocked=False):
    return policies.barrier_to_applying(
        opportunity, is_manager=is_manager, is_blocked=is_blocked, now=timezone.now()
    )


def test_an_open_job_can_be_applied_to():
    assert barrier(job()) is None
    assert barrier(job(deadline=timezone.now() + timedelta(minutes=1))) is None


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "DRAFT"},
        {"status": "CLOSED"},
        {"status": "EXPIRED"},
        {"status": "ARCHIVED"},
        {"moderation_status": "HIDDEN"},
        {"moderation_status": "REMOVED"},
        {"deadline": timezone.now() - timedelta(seconds=1)},
    ],
)
def test_a_job_that_is_not_open_takes_no_applications(fields):
    opportunity = job()
    for name, value in fields.items():
        setattr(opportunity, name, value)

    assert barrier(opportunity) is Barrier.NOT_ACCEPTING


def test_other_reasons_not_to_apply():
    assert barrier(job(method="EXTERNAL")) is Barrier.EXTERNAL
    assert barrier(job(), is_manager=True) is Barrier.OWN_JOB
    # A block looks exactly like a closed job.
    assert barrier(job(), is_blocked=True) is Barrier.NOT_ACCEPTING
    # Managing it is the reason given even if it is also closed.
    assert barrier(job(status="CLOSED"), is_manager=True) is Barrier.OWN_JOB
    assert set(policies.BARRIER_MESSAGES) == set(Barrier)


def test_only_jobs_take_applications():
    with pytest.raises(ValueError, match="Only jobs"):
        barrier(Opportunity(type="EVENT", status="PUBLISHED"))
