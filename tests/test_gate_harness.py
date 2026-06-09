from __future__ import annotations

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.gate import harness
from pcraft.core.gate.thresholds import Zone
from pcraft.testing import ScriptedVerifier


def test_parent_fail_forces_child_na(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier({"tabard": 0.05})  # tabard fails; sigil depends_on tabard
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds)
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["tabard"].zone is Zone.FAIL
    assert verdicts["sigil"].zone is Zone.NA  # not evaluated; not a false confirmation
    assert t.overall is Zone.FAIL


def test_all_pass_rolls_up_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier()  # affirm 0.95, negate 0.02 -> everything passes
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds)
    assert t.overall is Zone.PASS


def test_skipped_required_atom_is_uncertain_not_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)

    def scorer(q):
        if q.atom_id == "face":
            return None  # verifier cannot answer -> SKIPPED
        return 0.02 if q.polarity.value == "negate" else 0.95

    v = ScriptedVerifier(scorer)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds)
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["face"].zone is Zone.SKIPPED
    assert t.overall is Zone.UNCERTAIN  # an unconfirmed required atom never silently passes


def test_must_not_violation_fails(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    # the forbidden 'human face' IS present -> high score on a negate probe -> FAIL
    v = ScriptedVerifier({"no_human_face": 0.95})
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds)
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["no_human_face"].zone is Zone.FAIL
    assert t.overall is Zone.FAIL
