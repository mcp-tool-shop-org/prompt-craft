"""N of M required tiers executed — independent of the verdict."""

from __future__ import annotations

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.gate import harness
from pcraft.core.gate.thresholds import Zone
from pcraft.testing import ScriptedVerifier


def test_watchdog_counts_required_tiers_not_the_verdict(sprite_example):
    """⚑ REWRITTEN IN PLACE (amend wave 2, F-175c3b3e / F-d9b28ca6).

    This used to assert "A PASS that never ran Tier-0 is still a PASS, and the census says
    1 of 2" — i.e. it PINNED the hole: ``_pick`` fell forward from the missing Tier-0 onto the
    registered Tier-1 verifier, the fabricated score got graded against the palette band anyway,
    and the resulting PASS was the exact reason ``pcraft demo`` could print a green BOUND over a
    gate that only ran half its instruments. That was a bug wearing a test, not a spec.

    ``_pick`` no longer falls forward across tiers (F-175c3b3e): a required atom whose own tier
    never registered a verifier is SKIPPED, not silently scored on someone else's calibration.
    A SKIPPED required atom never rolls up to PASS (``_rollup``) — so the zone and the census
    now tell the SAME honest story instead of disagreeing. The census number is UNCHANGED (still
    1 of 2, because Tier-1's five other required atoms score fine) — what changed is that the
    verdict finally agrees with it, and the two facts are asserted here side by side, independent
    of each other, exactly as ``TierCensus``'s docstring says they must be.
    """
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier()  # only tier 1 registered; Tier-0 (palette) no longer falls forward onto it
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["palette"].zone is Zone.SKIPPED  # Tier-0 never ran; not graded on Tier-1's scale
    assert t.overall is Zone.UNCERTAIN  # no longer a silent PASS
    # The two facts stay separate (not folded into one another): the zone says UNCERTAIN on its
    # own merits (a required atom SKIPped); the census independently still says 1 of 2.
    assert t.tier_census.required == [0, 1]
    assert t.tier_census.executed == [1]
    assert t.tier_census.n == 1
    assert t.tier_census.m == 2


def test_watchdog_is_zero_of_m_when_nothing_scored(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: None)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert t.tier_census.n == 0
    assert t.tier_census.m == 2
    assert t.tier_census.executed == []


def test_watchdog_does_not_credit_an_unrequired_escalation_tier(sprite_example):
    """Tier 2 is escalation. Scoring on T1 does not list 2 as required."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t1 = ScriptedVerifier()
    t2 = ScriptedVerifier(family="dsg-qg", tier=2, verifier_id="scripted.dsg.v0")
    t = harness.evaluate(dag, "x.png", {1: t1, 2: t2}, thresholds, generator_family="stable-diffusion")
    assert 2 not in t.tier_census.required
    assert t.tier_census.executed == [1]
