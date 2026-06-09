from __future__ import annotations

import pytest

from pcraft.core.loop.compensators import CompensatorRegistry, default_registry
from pcraft.errors import PromptCraftError


def test_default_registry_covers_every_runtime_irreversible_action():
    reg = default_registry()
    for action in ("bind-to-canon", "records-write", "escalation-ticket", "encoder-rules-regen"):
        reg.require(action)  # no raise == a named compensator exists


def test_unregistered_irreversible_action_is_refused():
    reg = CompensatorRegistry()
    with pytest.raises(PromptCraftError) as exc:
        reg.require("publish-to-npm")
    assert exc.value.code == "STATE_NO_COMPENSATOR"


def test_every_compensator_names_an_owner_and_post_state():
    reg = default_registry()
    for action in reg.actions():
        comp = reg.get(action)
        assert comp.owner, f"{action} has no owner"
        assert comp.post_state, f"{action} has no post-rollback state"
        assert callable(comp.undo)
