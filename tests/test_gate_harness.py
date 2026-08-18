from __future__ import annotations

import math

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.contract.schema import Severity
from pcraft.core.gate import harness
from pcraft.core.gate.thresholds import Zone
from pcraft.testing import ScriptedVerifier, passing_verifiers


def test_parent_fail_forces_child_na(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier({"tabard": 0.05})  # tabard fails; sigil depends_on tabard
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["tabard"].zone is Zone.FAIL
    assert verdicts["sigil"].zone is Zone.NA  # not evaluated; not a false confirmation
    assert t.overall is Zone.FAIL


def test_all_pass_rolls_up_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    # Both required tiers registered: a lone Tier-1 verifier no longer covers Tier-0 atoms
    # (a missing wanted tier is SKIPPED, not fallen forward), so a PASS assertion has to
    # actually run the gate it claims passed.
    t = harness.evaluate(dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.PASS
    assert t.tier_census.n == t.tier_census.m


def test_skipped_required_atom_is_uncertain_not_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)

    def scorer(q):
        if q.atom_id == "face":
            return None  # verifier cannot answer -> SKIPPED
        return 0.02 if q.polarity.value == "negate" else 0.95

    v = ScriptedVerifier(scorer)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["face"].zone is Zone.SKIPPED
    assert t.overall is Zone.UNCERTAIN  # an unconfirmed required atom never silently passes


def test_must_not_violation_fails(sprite_example):
    """A violated REQUIRED negation rolls the whole transcript to FAIL.

    The severity is set here rather than inherited from the example contract, whose negations are
    `optional` because absence-verification is unmeasured on this stack. This test is about the
    mechanism, so it states its own premise instead of borrowing a policy that can change.
    """
    _s, resolved, thresholds, _c = sprite_example
    for mn in resolved.must_not:
        mn.severity = Severity.required
    dag = compile_questions(resolved)
    # the forbidden 'human face' IS present -> high score on a negate probe -> FAIL
    v = ScriptedVerifier({"no_human_face": 0.95})
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["no_human_face"].zone is Zone.FAIL
    assert t.overall is Zone.FAIL


# --------------------------------------------------------------------------- F-GATE-FEAT-003 wrap verifier.score(); reject NaN / out of range
# NaN used to compare False against both bands and fall through to UNCERTAIN.
# 1.5 used to clear the high band and become a false PASS.


def test_nan_score_is_skipped_not_uncertain(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: math.nan)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    scored = [x for x in t.verdicts if x.score is not None]
    assert scored == []
    # A SKIPPED parent still forces children to NA; none of them is a zoned score.
    assert all(x.zone in (Zone.SKIPPED, Zone.NA) for x in t.verdicts)
    assert t.overall is Zone.UNAVAILABLE
    assert any("rejected" in x.reason and "[0, 1]" in x.reason for x in t.verdicts)


def test_out_of_range_score_is_skipped_not_a_false_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: 1.5)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is not Zone.PASS
    assert all(x.score is None for x in t.verdicts)
    assert any("1.5" in x.reason for x in t.verdicts)


def test_negative_score_is_skipped_not_a_false_fail(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: -0.1)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert all(x.zone is not Zone.FAIL for x in t.verdicts)


def test_infinite_score_is_skipped(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: math.inf)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert all(x.score is None for x in t.verdicts)


def test_score_exception_is_skipped_not_a_crash(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)

    def boom(_q):
        raise RuntimeError("instrument exploded")

    v = ScriptedVerifier(boom)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert any("RuntimeError" in x.reason for x in t.verdicts)


def test_evaluate_stamps_the_thresholds_version(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion")
    assert t.thresholds_version == thresholds.version == "sprite.cal.v1"
