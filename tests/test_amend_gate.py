"""Regression tests for the wave-2 core-gate amend (dogfood swarm swarm-1787033129-beab).

Each test below pins one Director-approved fix to a HIGH finding from the wave-1 audit. Written
FIRST against the pre-fix code (all four failed red before ``harness.py`` / ``exit_contract.py``
were touched), per the amend method: red, then fix, then green.

  F-461c4198  the family guard protected only one of two doors (orchestrate.run(), not evaluate())
  F-175c3b3e  silent tier fall-forward graded a score on the wrong verifier's scale
  F-d9b28ca6  escalating Tier-1 -> Tier-2 erased the record that Tier-1 also ran
  (unlabelled) nothing consulted the tier census, so a half-run gate could still exit 0
"""

from __future__ import annotations

import pytest

from pcraft.core.contract.compile_questions import (
    CheckType,
    Polarity,
    Question,
    QuestionDAG,
    Severity,
    compile_questions,
)
from pcraft.core.gate import harness
from pcraft.core.gate.exit_contract import error_from_transcript
from pcraft.core.gate.harness import AtomVerdict, GateTranscript, TierCensus
from pcraft.core.gate.thresholds import Zone
from pcraft.errors import PromptCraftError
from pcraft.testing import ScriptedVerifier

# --------------------------------------------------------------------------------------------
# F-461c4198 -- the family guard must be enforced INSIDE evaluate(), not only by callers that
# remember to run it first. orchestrate.run() already called forbid_clipscore/assert_distinct_
# families before invoking the harness; the standalone `pcraft gate` CLI command imports harness
# directly and called neither. The guard now lives at the protected operation.
# --------------------------------------------------------------------------------------------


def test_evaluate_refuses_a_same_family_verifier(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(family="stable-diffusion", tier=1, verifier_id="scripted.same-family.v0")
    with pytest.raises(PromptCraftError) as exc:
        harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert exc.value.code == "GATE_SAME_FAMILY"


def test_evaluate_refuses_a_clipscore_family_verifier(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(family="clipscore", tier=1, verifier_id="scripted.clipscore.v0")
    # generator_family is deliberately a DIFFERENT family than the verifier, so a pass here
    # would prove nothing about the CLIPScore ban specifically -- only forbid_clipscore blocks it.
    with pytest.raises(PromptCraftError) as exc:
        harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert exc.value.code == "GATE_CLIPSCORE_BANNED"


def test_evaluate_still_runs_with_distinct_families(sprite_example):
    """Sanity: the new required kwarg does not itself change gate behaviour when families differ."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier()  # family "clip-flant5", distinct from the generator family below
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert isinstance(t, GateTranscript)


def test_generator_family_is_required_keyword_only(sprite_example):
    """Pinned so a future edit cannot quietly reintroduce a default and paper over the gap."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier()
    with pytest.raises(TypeError):
        harness.evaluate(dag, "x.png", {v.tier: v}, thresholds)  # type: ignore[call-arg]


# --------------------------------------------------------------------------------------------
# F-175c3b3e -- _pick used to fall forward to whatever tier WAS registered, and the resulting
# score was graded against the band keyed by the atom's check_type -- not the verifier that
# produced the number. Real shipped bands (sprite.calibration.json): siglip2 high=0.10/low=0.01,
# vqa high=0.80/low=0.40 -- almost an order of magnitude apart. Both directions pinned below,
# using the live shipped bands so a future calibration edit that closed the gap would be visible
# here rather than silently invalidating the regression.
# --------------------------------------------------------------------------------------------


def test_a_required_vqa_atom_is_skipped_not_graded_on_the_siglip2_scale(sprite_example):
    """Direction 1 of F-175c3b3e: a Tier-0 SigLIP2-family verifier standing in for a required
    vqa atom used to score 0.12 -- a confident 'yes' on SigLIP2's own scale (its own high band
    is 0.10) -- and get graded a false FAIL against the vqa band (low=0.40, 0.12 <= 0.40)."""
    _s, _resolved, thresholds, _c = sprite_example
    band = thresholds.band_for("vqa")
    assert (band.low, band.high) == (0.40, 0.80)  # pin the real shipped band this defect exploited
    q = Question(
        atom_id="pose", text="Does this show the pose?",
        check_type=CheckType.vqa, polarity=Polarity.affirm, severity=Severity.required,
    )
    dag = QuestionDAG(contract_id="test:pin-175c3b3e-vqa", questions=[q])
    siglip_verifier = ScriptedVerifier(lambda _q: 0.12, family="siglip2", tier=0, verifier_id="scripted.siglip2.v0")
    t = harness.evaluate(dag, "x.png", {0: siglip_verifier}, thresholds, generator_family="stable-diffusion")
    v = t.verdicts[0]
    assert v.zone is Zone.SKIPPED  # not a false FAIL against a band it was never calibrated for
    assert v.score is None
    assert v.tier_used is None
    # This DAG has exactly one required atom, and it SKIPped -- zero required atoms scored, so
    # the roll-up is UNAVAILABLE (0 of M), not UNCERTAIN (_rollup's own documented distinction).
    # Either way it is never the false FAIL the old fall-forward produced.
    assert t.overall is Zone.UNAVAILABLE
    assert t.could_not_run() is True


def test_a_required_siglip2_atom_is_skipped_not_graded_on_the_vqa_scale(sprite_example):
    """Direction 2 of F-175c3b3e: a Tier-1 VQA-family verifier standing in for a required
    siglip2 atom used to score 0.5 -- a middling, actually-UNCERTAIN value on VQA's own scale --
    and get graded a false, confident PASS against the siglip2 band (high=0.10, 0.5 >= 0.10)."""
    _s, _resolved, thresholds, _c = sprite_example
    band = thresholds.band_for("siglip2")
    assert (band.low, band.high) == (0.01, 0.10)  # pin the real shipped band this defect exploited
    q = Question(
        atom_id="silhouette", text="Does this show the silhouette?",
        check_type=CheckType.siglip2, polarity=Polarity.affirm, severity=Severity.required,
    )
    dag = QuestionDAG(contract_id="test:pin-175c3b3e-siglip2", questions=[q])
    vqa_verifier = ScriptedVerifier(lambda _q: 0.5, family="clip-flant5", tier=1, verifier_id="scripted.vqa.v0")
    t = harness.evaluate(dag, "x.png", {1: vqa_verifier}, thresholds, generator_family="stable-diffusion")
    v = t.verdicts[0]
    assert v.zone is Zone.SKIPPED  # not a false PASS against a band it was never calibrated for
    assert v.score is None
    assert v.tier_used is None
    # One required atom, SKIPped -- zero required atoms scored, so UNAVAILABLE (0 of M), not
    # UNCERTAIN. Either way it is never the false PASS the old fall-forward produced.
    assert t.overall is Zone.UNAVAILABLE
    assert t.could_not_run() is True


# --------------------------------------------------------------------------------------------
# F-d9b28ca6 -- escalating a borderline Tier-1 result to Tier-2 overwrote used_tier with 2
# before the AtomVerdict was built, so the census only ever saw the LAST tier, not every tier
# that actually scored. The atom checked MOST thoroughly (both tiers ran and agreed) was the one
# case the watchdog reported as never-executed.
# --------------------------------------------------------------------------------------------


def test_escalation_still_credits_the_atoms_required_tier_in_the_census(sprite_example):
    _s, _resolved, thresholds, _c = sprite_example
    q = Question(
        atom_id="face", text="Does this show the face?",
        check_type=CheckType.vqa, polarity=Polarity.affirm, severity=Severity.required,
    )
    dag = QuestionDAG(contract_id="test:pin-d9b28ca6", questions=[q])
    tier1 = ScriptedVerifier(lambda _q: 0.6, family="clip-flant5", tier=1, verifier_id="scripted.vqa.v0")  # UNCERTAIN -> escalates
    tier2 = ScriptedVerifier(lambda _q: 0.9, family="dsg-qg", tier=2, verifier_id="scripted.dsg.v0")  # confirms PASS
    t = harness.evaluate(dag, "x.png", {1: tier1, 2: tier2}, thresholds, generator_family="stable-diffusion")
    v = t.verdicts[0]
    assert v.tier_used == 2  # the escalated tier still decides the verdict/score
    assert v.zone is Zone.PASS
    assert v.tiers_consulted == [1, 2]  # ...but Tier-1's run is not erased from the record
    assert t.tier_census.required == [1]
    assert t.tier_census.executed == [1]  # the watchdog credits the atom's own required tier
    assert t.tier_census.n == t.tier_census.m == 1


# --------------------------------------------------------------------------------------------
# "Nothing consults the census" -- tier_census and Zone are documented as two independent facts
# (TierCensus's own docstring), but error_from_transcript never looked at the census, so a gate
# that under-ran its own instruments could still exit 0 if every atom that DID score happened to
# pass (this is what made `pcraft demo` print "tiers executed: 1 of 2" / "decision: BOUND", exit
# 0). The first two tests below build a GateTranscript BY HAND rather than via evaluate(): after
# the F-175c3b3e and F-d9b28ca6 fixes above, evaluate() can no longer actually produce a PASS
# with an incomplete census (any required atom that truly SKIPs now forces the zone to
# UNCERTAIN on its own) -- so this is a deliberate defence-in-depth net, pinned directly against
# exit_contract's own invariant so a future change to _rollup/_counts cannot reopen the gap
# without this test catching it. The third test is the end-to-end shape of the reported symptom.
# --------------------------------------------------------------------------------------------


def _one_atom_verdict(**overrides) -> AtomVerdict:
    base = dict(
        atom_id="palette", polarity=Polarity.affirm, severity=Severity.required,
        score=0.95, zone=Zone.PASS, tier_used=1, tiers_consulted=[1],
        verifier_id="scripted.vqa.v0", reason="score 0.9500 -> PASS",
    )
    base.update(overrides)
    return AtomVerdict(**base)


def test_exit_contract_refuses_exit_zero_when_the_census_is_short():
    transcript = GateTranscript(
        contract_id="test:census-gap", overall=Zone.PASS, verdicts=[_one_atom_verdict()],
        tier_census=TierCensus(required=[0, 1], executed=[1]),  # Tier-0 never ran
    )
    err = error_from_transcript(transcript)
    assert err is not None
    assert err.code == "PARTIAL_TIER_CENSUS"
    assert err.exit_code == 3  # PARTIAL_, not 0 and not folded into GATE_UNAVAILABLE's 4


def test_exit_contract_allows_exit_zero_when_the_census_is_complete():
    transcript = GateTranscript(
        contract_id="test:census-complete", overall=Zone.PASS, verdicts=[_one_atom_verdict()],
        tier_census=TierCensus(required=[1], executed=[1]),
    )
    assert error_from_transcript(transcript) is None


def test_demo_shaped_partial_run_is_not_exit_zero(sprite_example):
    """End-to-end shape of the reported symptom: only a Tier-1 verifier registered, so the
    contract's Tier-0 atom (palette) never runs. Must not exit 0."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier()  # tier 1 only
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.tier_census.n < t.tier_census.m
    err = error_from_transcript(t)
    assert err is not None
    assert err.exit_code != 0
