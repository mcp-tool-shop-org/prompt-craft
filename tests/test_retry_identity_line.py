"""The atom / identity line, in the repair router.

The Director ruled the distinction holds. A presence atom whose id contains
the substring 'face' is not the identity_ref plate. Routing it to
STRENGTHEN_IDENTITY is identity work by the back door.
"""

from __future__ import annotations

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.gate import harness
from pcraft.core.loop.retry_policy import (
    RepairAction,
    RetryBudget,
    _is_identity_atom,
    choose_repair,
)
from pcraft.testing import ScriptedVerifier


def test_face_is_not_an_identity_atom():
    assert _is_identity_atom("face") is False
    assert _is_identity_atom("no_human_face") is False
    assert _is_identity_atom("palette") is False
    assert _is_identity_atom("sigil") is False


def test_only_an_identity_id_requests_the_plate_bump():
    assert _is_identity_atom("identity") is True
    assert _is_identity_atom("identity_ref") is True


def test_a_failed_face_atom_does_not_strengthen_the_plate(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier({"face": 0.05})
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds)
    action = choose_repair(t, RetryBudget(), dag)
    assert action is not RepairAction.STRENGTHEN_IDENTITY
