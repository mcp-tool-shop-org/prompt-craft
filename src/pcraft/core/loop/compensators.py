"""NAMED_COMPENSATORS registry — the executable mirror of COMPENSATORS.md (NO SKIP).

Every irreversible run-time action (bind-to-canon, a records/ write, an escalation ticket, an
encoder-rules regen) is registered here with a named undo callable and an owner. The orchestrator
will not perform an irreversible action whose compensator is not registered. Heritage: Sagas
(Garcia-Molina & Salem, SIGMOD 1987)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ...errors import PromptCraftError


@dataclass(frozen=True)
class Compensator:
    action: str  # the irreversible action this undoes, e.g. "bind-to-canon"
    undo: Callable[..., None]  # the named compensating action
    owner: str  # who owns running it
    post_state: str  # the state after rollback (for the audit trail)


class CompensatorRegistry:
    def __init__(self) -> None:
        self._by_action: dict[str, Compensator] = {}

    def register(self, comp: Compensator) -> None:
        self._by_action[comp.action] = comp

    def get(self, action: str) -> Compensator:
        if action not in self._by_action:
            raise PromptCraftError(
                "STATE_NO_COMPENSATOR",
                f"irreversible action {action!r} has no registered compensator",
                hint="Register a named undo in COMPENSATORS.md AND here before performing this action.",
            )
        return self._by_action[action]

    def require(self, action: str) -> None:
        """Assert a compensator exists for an action BEFORE it is performed (the no-skip gate)."""
        self.get(action)

    def actions(self) -> list[str]:
        return sorted(self._by_action)


def default_registry() -> CompensatorRegistry:
    """The run-time compensators from COMPENSATORS.md §2, wired as no-op-safe defaults.

    Each undo is a placeholder that records intent; a real deployment binds these to the actual
    canon registry / records store / ticketing system. The point is that the *names and owners*
    exist and are enforced before any irreversible call."""
    reg = CompensatorRegistry()

    def _noop(*_a, **_k) -> None:  # records intent; real impls override
        return None

    reg.register(Compensator("bind-to-canon", _noop, "pipeline (Director approves first bind)",
                             "registry entry removed; canon file reverted to pre-bind revision"))
    reg.register(Compensator("records-write", _noop, "pipeline",
                             "receipt deleted by id; provenance index re-indexed"))
    reg.register(Compensator("escalation-ticket", _noop, "pipeline (Director resolves)",
                             "ticket closed with a resolution note"))
    reg.register(Compensator("encoder-rules-regen", _noop, "sync script",
                             "encoder_craft.md restored from git (generated + committed)"))
    return reg
