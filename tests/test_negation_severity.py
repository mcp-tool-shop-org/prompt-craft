"""A negation's blocking power tracks the evidence behind the check enforcing it.

Confirming a thing is *absent* is a different capability from confirming it is present, and the
less established of the two: CLIP-family encoders are documented as limited at negation
(TNG-CLIP, arXiv:2505.18434), and no located source benchmarks a sigmoid zero-shot score as an
absence verifier. So `MustNot` carries a severity, and a negation whose verifier is not yet
measured on absence reports without blocking.

These tests exist because the schema change ALONE was cosmetic. Two sites in the harness read
`severity is required OR polarity is negate`, and that `or` overrode severity — an atom would
read `optional` in the contract and still block a bind. The fixtures below are written to fail
if either site regresses to that form.
"""

from __future__ import annotations

import json

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.contract.schema import MustNot, Severity
from pcraft.core.gate import harness
from pcraft.core.gate.exit_contract import error_from_transcript
from pcraft.core.gate.thresholds import Zone
from pcraft.testing import ScriptedVerifier

_CONTRACTS = "src/pcraft/domains/image/subdomains/sprite/contracts"


def test_a_negation_without_a_severity_is_still_required():
    """Backward compatibility is the load-bearing guarantee of this change.

    What this looks like if wrong: someone flips the default to `optional` for convenience and
    every contract written before the field silently stops blocking on its anti-constraints.
    """
    assert MustNot(id="no_x", claim="an x").severity is Severity.required


def test_an_optional_negation_compiles_to_an_optional_question():
    """The severity has to survive compilation, not just parse."""
    mn = MustNot(id="no_x", claim="an x", severity=Severity.optional)
    assert mn.severity is Severity.optional


def test_an_optional_negation_that_fails_does_not_block(sprite_example):
    """⚑ The test that catches the cosmetic change.

    A violated OPTIONAL negation must not reach the blocking set. If `_counts` regresses to
    `severity is required or polarity is negate`, this fails — the atom reads optional in the
    contract and blocks anyway.
    """
    _s, resolved, thresholds, _c = sprite_example
    for mn in resolved.must_not:
        mn.severity = Severity.optional
    dag = compile_questions(resolved)

    # every affirmation passes; every negation is maximally violated
    def scorer(q):
        return 0.99  # high on a negate probe == the forbidden thing IS present

    t = harness.evaluate(dag, "x.png", {0: ScriptedVerifier(scorer), 1: ScriptedVerifier(scorer)}, thresholds)

    violated = [v for v in t.verdicts if v.polarity.value == "negate" and v.zone is Zone.FAIL]
    assert violated, "the fixture must actually violate the negations or it proves nothing"
    assert not [v for v in t.failed_required() if v.polarity.value == "negate"], (
        "an optional negation reached the blocking set"
    )


def test_a_required_negation_that_fails_still_blocks(sprite_example):
    """The other direction. The fix must not disarm negations generally.

    Without this, `_counts` could be narrowed to `severity is required` on an atom whose severity
    was never set from the contract, and every negation would go quiet.
    """
    _s, resolved, thresholds, _c = sprite_example
    for mn in resolved.must_not:
        mn.severity = Severity.required
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", {0: ScriptedVerifier(lambda _q: 0.99), 1: ScriptedVerifier(lambda _q: 0.99)}, thresholds
    )
    assert [v for v in t.failed_required() if v.polarity.value == "negate"]
    err = error_from_transcript(t)
    assert err is not None and err.code == "GATE_FAIL"


def test_an_optional_negations_tier_is_not_a_required_tier(sprite_example):
    """The census denominator must not count a tier only an optional atom needs.

    What this looks like if wrong: the watchdog reports a tier as required-but-not-executed and
    reads like a dead verifier, when nothing blocking ever needed it.
    """
    _s, resolved, thresholds, _c = sprite_example
    for mn in resolved.must_not:
        mn.severity = Severity.optional
    for atom in resolved.must_have:
        atom.severity = Severity.optional
    dag = compile_questions(resolved)
    t = harness.evaluate(dag, "x.png", {1: ScriptedVerifier(lambda _q: 0.99)}, thresholds)
    assert t.tier_census.required == [], "no atom is required, so no tier is required"


def test_the_scaffold_contracts_declare_their_negations_optional():
    """The shipped example contracts practise what the schema documents.

    Absence-verification is unmeasured on this stack, so these four run and report rather than
    block. They are raised to `required` when a verifier is calibrated for absence.
    """
    expected = {
        f"{_CONTRACTS}/characters/example.character.contract.json": {"no_human_face", "no_shield"},
        f"{_CONTRACTS}/factions/example.faction.contract.json": {"no_rival_colours", "no_modern_gear"},
    }
    for path, ids in expected.items():
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        seen = {mn["id"]: mn.get("severity") for mn in doc["must_not"]}
        assert set(seen) == ids, f"{path} negation set changed: {sorted(seen)}"
        assert all(v == "optional" for v in seen.values()), f"{path}: {seen}"
