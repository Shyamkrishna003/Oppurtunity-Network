from dataclasses import dataclass

import pytest
from rest_framework.exceptions import PermissionDenied

from common.errors import BusinessRuleViolation, InvalidTransition, StaleState
from common.state_machine import StateMachine, Transition


@dataclass
class Ticket:
    status: str = "OPEN"
    owner: str = "alice"
    ready: bool = True


def _is_owner(actor, ticket):
    return actor == ticket.owner


def _must_be_ready(ticket):
    if not ticket.ready:
        raise BusinessRuleViolation("Ticket is not ready.", code="not_ready")


MACHINE = StateMachine(
    "ticket",
    [
        Transition("OPEN", "IN_PROGRESS", policy=_is_owner, guard=_must_be_ready),
        Transition("IN_PROGRESS", "DONE"),
        Transition("OPEN", "CANCELLED"),
    ],
)
STATES = ["OPEN", "IN_PROGRESS", "DONE", "CANCELLED"]
VALID = {("OPEN", "IN_PROGRESS"), ("IN_PROGRESS", "DONE"), ("OPEN", "CANCELLED")}


@pytest.mark.parametrize(("source", "target"), sorted(VALID))
def test_valid_transitions_change_state(source, target):
    ticket = Ticket(status=source)

    assert MACHINE.apply(ticket, target, actor="alice") is True
    assert ticket.status == target


@pytest.mark.parametrize(
    ("source", "target"),
    [(s, t) for s in STATES for t in STATES if s != t and (s, t) not in VALID],
)
def test_every_other_pair_is_rejected(source, target):
    ticket = Ticket(status=source)

    with pytest.raises(InvalidTransition):
        MACHINE.apply(ticket, target, actor="alice")
    assert ticket.status == source


def test_replaying_the_current_state_is_a_noop():
    ticket = Ticket(status="DONE")

    assert MACHINE.apply(ticket, "DONE") is False
    assert ticket.status == "DONE"


def test_stale_expected_state_is_rejected_before_anything_else():
    ticket = Ticket(status="IN_PROGRESS")

    with pytest.raises(StaleState):
        MACHINE.apply(ticket, "DONE", expected="OPEN")
    assert ticket.status == "IN_PROGRESS"


def test_policy_denies_other_actors():
    ticket = Ticket()

    with pytest.raises(PermissionDenied):
        MACHINE.apply(ticket, "IN_PROGRESS", actor="mallory")
    assert ticket.status == "OPEN"


def test_guard_failure_leaves_state_unchanged():
    ticket = Ticket(ready=False)

    with pytest.raises(BusinessRuleViolation):
        MACHINE.apply(ticket, "IN_PROGRESS", actor="alice")
    assert ticket.status == "OPEN"


def test_targets_and_terminal_states():
    assert MACHINE.targets("OPEN") == {"IN_PROGRESS", "CANCELLED"}
    assert MACHINE.is_terminal("DONE")
    assert not MACHINE.is_terminal("OPEN")


def test_duplicate_transitions_are_a_definition_error():
    with pytest.raises(ValueError, match="duplicate transition"):
        StateMachine("broken", [Transition("A", "B"), Transition("A", "B")])
