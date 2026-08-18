"""N of M required tiers executed — independent of the verdict."""

from __future__ import annotations

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.gate import harness
from pcraft.core.gate.thresholds import Zone
from pcraft.testing import ScriptedVerifier


def test_watchdog_counts_required_tiers_not_the_verdict(sprite_example):
    """A PASS that never ran Tier-0 is still a PASS, and the census says 1 of 2."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier()  # only tier 1; _pick falls forward for palette/siglip2
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds)
    assert t.overall is Zone.PASS
    assert t.tier_census.required == [0, 1]
    assert t.tier_census.executed == [1]
    assert t.tier_census.n == 1
    assert t.tier_census.m == 2


def test_watchdog_is_zero_of_m_when_nothing_scored(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: None)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds)
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
    t = harness.evaluate(dag, "x.png", {1: t1, 2: t2}, thresholds)
    assert 2 not in t.tier_census.required
    assert t.tier_census.executed == [1]
