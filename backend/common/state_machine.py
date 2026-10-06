"""Declarative state machines shared by every domain workflow.

A machine only decides whether a transition is legal and mutates the status attribute.
The calling service owns everything around it, in this order:

1. open ``transaction.atomic()`` and load the row with ``select_for_update()``;
2. call ``machine.apply(...)``;
3. save, write history and audit rows, create notifications;
4. enqueue external effects with ``transaction.on_commit``.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from rest_framework.exceptions import PermissionDenied

from common.errors import InvalidTransition, StaleState

# (actor, obj) -> allowed. ``actor`` is None for system-driven transitions.
Policy = Callable[[Any, Any], bool]
# (obj) -> None; raises BusinessRuleViolation when a precondition fails.
Guard = Callable[[Any], None]


@dataclass(frozen=True)
class Transition:
    source: str
    target: str
    policy: Policy | None = None
    guard: Guard | None = None


class StateMachine:
    def __init__(self, name: str, transitions: Iterable[Transition], field: str = "status") -> None:
        self.name = name
        self.field = field
        self._transitions: dict[tuple[str, str], Transition] = {}
        for transition in transitions:
            key = (transition.source, transition.target)
            if key in self._transitions:
                raise ValueError(f"{name}: duplicate transition {key[0]} -> {key[1]}")
            self._transitions[key] = transition

    def targets(self, source: str) -> set[str]:
        return {target for (src, target) in self._transitions if src == source}

    def is_terminal(self, state: str) -> bool:
        return not self.targets(state)

    def apply(
        self,
        obj: Any,
        target: str,
        *,
        actor: Any = None,
        expected: str | None = None,
    ) -> bool:
        """Move ``obj`` to ``target``. Returns False when it is already there (idempotent replay).

        ``obj`` must be locked by the caller; ``expected`` is the state the client last saw.
        """
        current: str = getattr(obj, self.field)
        if expected is not None and current != expected:
            raise StaleState()
        if current == target:
            return False

        transition = self._transitions.get((current, target))
        if transition is None:
            raise InvalidTransition(f"{self.name}: cannot move from {current} to {target}.")
        if transition.policy is not None and not transition.policy(actor, obj):
            raise PermissionDenied()
        if transition.guard is not None:
            transition.guard(obj)

        setattr(obj, self.field, target)
        return True
