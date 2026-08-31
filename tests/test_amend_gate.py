"""Regression tests for the wave-2 core-gate amend (dogfood swarm swarm-1787033129-beab).

Each test below pins one Director-approved fix to a HIGH finding from the wave-1 audit. Written
FIRST against the pre-fix code (all four failed red before ``harness.py`` / ``exit_contract.py``
were touched), per the amend method: red, then fix, then green.

  F-461c4198  the family guard protected only one of two doors (orchestrate.run(), not evaluate())
  F-175c3b3e  silent tier fall-forward graded a score on the wrong verifier's scale
  F-d9b28ca6  escalating Tier-1 -> Tier-2 erased the record that Tier-1 also ran
  (unlabelled) nothing consulted the tier census, so a half-run gate could still exit 0
  F-19f97de2  a dangling depends_on silently deleted the edge instead of failing closed

A later wave (swarm-1788165870-6880) added the seam the isolated fixes could not see, plus
the output-surface half of the cp437 sweep:

  F-2b317b56  depends_on integrity was closed one way only -- an ACYCLIC check existed
              nowhere on the gate path, and QuestionDAG.topological()'s bare ValueError
              escaped evaluate() as RUNTIME_UNEXPECTED at exit 2
  F-a6acaab1  the em-dash sweep covered --help pages and DEFAULT_HINTS but not the strings
              the RUNTIME surface prints -- checkpoint.text is the hottest of them
  F-09f30018  a guard that does not say whether it is reachable reads as dead code
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

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
from pcraft.core.gate.checkpoint import build_checkpoint
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
    base = {
        "atom_id": "palette", "polarity": Polarity.affirm, "severity": Severity.required,
        "score": 0.95, "zone": Zone.PASS, "tier_used": 1, "tiers_consulted": [1],
        "verifier_id": "scripted.vqa.v0", "reason": "score 0.9500 -> PASS",
    }
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


# --------------------------------------------------------------------------------------------
# F-19f97de2 -- the parent-gating branch read `if q.depends_on and q.depends_on in verdicts:`.
# The `in verdicts` clause silently turned "the declared parent could not be resolved" into
# "this atom has no parent": the edge was DELETED, with no error, no SKIPPED, and no reason
# string recording that it had been dropped. Nothing upstream catches it either --
# QuestionDAG.topological() applies the identical `depends_on in index` guard, so evaluate()
# never even KeyErrors. A one-character typo in a depends_on therefore promoted a child from
# "not evaluated, because its parent is absent" to "independently confirmed".
#
# Both directions are pinned below. The harness half is the fail-closed net; a load-time
# referential check on depends_on is the other half of this fix and lives in
# core/contract/loader.py (a different domain, landed in parallel).
# --------------------------------------------------------------------------------------------


def _parent_child_dag(*, depends_on: str, parent_severity: Severity) -> QuestionDAG:
    """tabard (the parent) -> sigil (the child), plus an unrelated required atom that scores.

    The third atom is load-bearing, not decoration: with only tabard+sigil present, every
    required atom ends up unscored and ``_rollup`` reports UNAVAILABLE, which masks the flip
    this test exists to catch. ``silhouette`` keeps at least one required score on the books so
    the roll-up is decided by the child's zone -- the same shape the shipped sprite contract has.
    """
    return QuestionDAG(
        contract_id="test:pin-19f97de2",
        questions=[
            Question(
                atom_id="tabard", text="Does this show a crimson tabard?",
                check_type=CheckType.vqa, polarity=Polarity.affirm, severity=parent_severity,
            ),
            Question(
                atom_id="sigil", text="Does this show a sigil on the tabard?",
                check_type=CheckType.vqa, polarity=Polarity.affirm, severity=Severity.required,
                depends_on=depends_on,
            ),
            Question(
                atom_id="silhouette", text="Does this show the silhouette?",
                check_type=CheckType.vqa, polarity=Polarity.affirm, severity=Severity.required,
            ),
        ],
    )


# tabard is absent (0.01 <= the vqa band's low of 0.40 -> FAIL); everything else reads present.
_SIGIL_SCORES = {"tabard": 0.01, "sigil": 0.95, "silhouette": 0.95}


def _evaluate_sigil_dag(thresholds, *, depends_on: str, parent_severity: Severity):
    v = ScriptedVerifier(_SIGIL_SCORES, family="clip-flant5", tier=1, verifier_id="scripted.vqa.v0")
    dag = _parent_child_dag(depends_on=depends_on, parent_severity=parent_severity)
    t = harness.evaluate(dag, "x.png", {1: v}, thresholds, generator_family="stable-diffusion")
    return t, {x.atom_id: x for x in t.verdicts}


def test_an_intact_failing_parent_still_forces_the_child_to_na(sprite_example):
    """Direction 1: the behaviour the fix must NOT disturb. A parent that resolves and fails
    still gates its child to NA with the existing 'did not pass' reason -- SKIPPED is reserved
    for a parent that could not be resolved at all, so the two causes stay distinguishable in
    the transcript."""
    _s, _resolved, thresholds, _c = sprite_example
    t, verdicts = _evaluate_sigil_dag(thresholds, depends_on="tabard", parent_severity=Severity.required)
    assert verdicts["tabard"].zone is Zone.FAIL
    assert verdicts["sigil"].zone is Zone.NA
    assert verdicts["sigil"].score is None
    assert "did not pass" in verdicts["sigil"].reason
    assert t.overall is Zone.FAIL  # the required parent's own failure still decides the roll-up


def test_a_dangling_depends_on_is_skipped_not_silently_unparented(sprite_example):
    """Direction 2: a depends_on that names no atom in this contract must fail CLOSED.

    Before the fix the child was scored independently and returned PASS 0.95 -- the gate
    confirming a sigil on a tabard it had just decided was absent. SKIPPED already never rolls
    up to PASS, so routing an unresolvable parent there closes the hole without a new zone, and
    the reason string names the id that did not resolve instead of dropping the edge in silence.
    """
    _s, _resolved, thresholds, _c = sprite_example
    t, verdicts = _evaluate_sigil_dag(
        thresholds, depends_on="tabard_typo", parent_severity=Severity.required
    )
    assert verdicts["sigil"].zone is Zone.SKIPPED, (
        "an unresolvable parent must not read as 'this atom has no parent'"
    )
    assert verdicts["sigil"].score is None, "the child must not be scored independently"
    assert "tabard_typo" in verdicts["sigil"].reason, "the dropped edge has to be named"
    assert t.overall is not Zone.PASS


def test_a_dangling_depends_on_cannot_flip_amend_into_advance(sprite_example):
    """The measured consequence, end to end: a one-character typo flipped the loop verdict from
    AMEND (escalate to a human) to ADVANCE (bind to canon).

    The parent is ``optional`` here so it does not block on its own -- that is what let the
    child's false PASS decide the roll-up. The tier census is complete in BOTH runs, so the
    ANDON watchdog never fired and nothing else in the stack caught it.
    """
    from pcraft.core.loop.retry_policy import Verdict, verdict_from_transcript

    _s, _resolved, thresholds, _c = sprite_example
    intact, intact_verdicts = _evaluate_sigil_dag(
        thresholds, depends_on="tabard", parent_severity=Severity.optional
    )
    dangling, _dangling_verdicts = _evaluate_sigil_dag(
        thresholds, depends_on="tabard_typo", parent_severity=Severity.optional
    )

    # the census is clean either way -- this defect was never visible to the watchdog
    assert intact.tier_census.n == intact.tier_census.m
    assert dangling.tier_census.n == dangling.tier_census.m

    assert intact_verdicts["sigil"].zone is Zone.NA
    assert intact.overall is Zone.UNCERTAIN
    assert verdict_from_transcript(intact) is Verdict.AMEND

    assert dangling.overall is not Zone.PASS, "a dropped edge must not manufacture a clean gate"
    assert verdict_from_transcript(dangling) is Verdict.AMEND, (
        "a typo in depends_on must never be the difference between escalate and bind"
    )


# --------------------------------------------------------------------------------------------
# F-2b317b56 -- depends_on referential integrity was closed in ONE direction only. The loader
# refuses a parent that does not exist and the harness fails closed with SKIPPED (F-19f97de2
# above), but neither half asked whether the surviving edges are ACYCLIC. The acyclicity check
# lived downstream in QuestionDAG.topological() as a bare `raise ValueError(...)` -- an
# exception from outside the PromptCraftError hierarchy -- and evaluate() called that method
# unguarded, in deliberate contrast to _safe_score three lines below it, which is careful to
# classify every exception a verifier can throw.
#
# Measured before the fix, on a two-atom contract with tabard.depends_on='sigil' and
# sigil.depends_on='tabard': `pcraft bind --mock` and `pcraft gate <image>` both died with
# error[RUNTIME_UNEXPECTED] at exit 2 -- the backstop code, on a plain contract-authoring typo
# that errors.py's namespace table puts at exit 1 with a CONTRACT_ code.
#
# This is the harness half. A load-time refusal is the other half and lives in the contract
# domain; the tests below construct the cycle directly against QuestionDAG so they pin THIS
# door whatever that one does -- which is also the only door a library caller who builds a DAG
# himself ever reaches.
# --------------------------------------------------------------------------------------------


def _cyclic_dag(*, self_edge: bool = False) -> QuestionDAG:
    """tabard <-> sigil (or tabard -> tabard), closed by mutation AFTER construction.

    Same convention test_amend_contract.py uses to reach a state the loader refuses
    (``character.must_have[0].severity = "advisory"``): build the legal object, then set the
    field. Building it cyclic in the constructor would couple this regression to whatever
    validator the load-time half installs, and the point here is the gate's own net.
    """
    dag = QuestionDAG(
        contract_id="test:pin-2b317b56",
        questions=[
            Question(
                atom_id="tabard", text="Does this show a crimson tabard?",
                check_type=CheckType.vqa, polarity=Polarity.affirm, severity=Severity.required,
            ),
            Question(
                atom_id="sigil", text="Does this show a sigil on the tabard?",
                check_type=CheckType.vqa, polarity=Polarity.affirm, severity=Severity.required,
                depends_on="tabard",
            ),
        ],
    )
    dag.by_id("tabard").depends_on = "tabard" if self_edge else "sigil"
    return dag


def _evaluate_cyclic(thresholds, *, self_edge: bool = False):
    v = ScriptedVerifier(family="clip-flant5", tier=1, verifier_id="scripted.vqa.v0")
    return harness.evaluate(
        _cyclic_dag(self_edge=self_edge), "x.png", {1: v}, thresholds,
        generator_family="stable-diffusion",
    )


def test_a_dependency_cycle_at_the_gate_is_a_coded_refusal_not_a_bare_valueerror(sprite_example):
    """The exception class is the whole finding. A bare ValueError out of evaluate() lands on
    the CLI's `except Exception` backstop and is reported as RUNTIME_UNEXPECTED at exit 2 --
    whose own hint says "this code is the backstop, not a diagnosis" -- for what is a plain
    contract-authoring typo."""
    _s, _resolved, thresholds, _c = sprite_example
    with pytest.raises(PromptCraftError) as exc:
        _evaluate_cyclic(thresholds)
    assert not isinstance(exc.value, ValueError), "the refusal must not BE the raw ValueError"
    assert exc.value.code.startswith("CONTRACT_"), (
        f"a cyclic depends_on is a contract defect, not a runtime crash; got {exc.value.code}"
    )
    assert exc.value.exit_code == 1, "exit 1 (fix your input), not the RUNTIME_ backstop's 2"


def test_the_cycle_refusal_names_the_cycle_and_carries_a_hint(sprite_example):
    """A distinct code with no distinct guidance is half a refusal (the standard this repo
    already applied to IO_RECORD_SCHEMA_UNSUPPORTED). The message has to name an atom on the
    cycle, or the author has nothing to go and edit."""
    _s, _resolved, thresholds, _c = sprite_example
    with pytest.raises(PromptCraftError) as exc:
        _evaluate_cyclic(thresholds)
    text = exc.value.to_safe_text()
    assert "tabard" in text or "sigil" in text, "the refusal must name an atom on the cycle"
    assert exc.value.hint, "the code needs a DEFAULT_HINTS entry, not just a name"
    assert "hint:" in text


def test_a_self_referential_depends_on_takes_the_same_path(sprite_example):
    """``a.depends_on == 'a'`` reaches topological()'s cycle branch by the identical route and
    must not be a different answer."""
    _s, _resolved, thresholds, _c = sprite_example
    with pytest.raises(PromptCraftError) as exc:
        _evaluate_cyclic(thresholds, self_edge=True)
    assert exc.value.code.startswith("CONTRACT_")
    assert exc.value.exit_code == 1


def test_evaluate_terminates_on_a_cycle_rather_than_walking_it(sprite_example):
    """The other failure mode a graph walk can have. Whatever the guard does, it must be an
    ANSWER: never a hang, never an unbounded walk. Pinned by the fact that the call returns
    control at all -- if it looped, the suite would time out here rather than fail."""
    _s, _resolved, thresholds, _c = sprite_example
    for self_edge in (False, True):
        with pytest.raises(PromptCraftError):
            _evaluate_cyclic(thresholds, self_edge=self_edge)


def test_an_ordinary_parent_child_dag_still_evaluates(sprite_example):
    """Collateral guard: the acyclicity net must not refuse the edges depends_on exists for."""
    _s, _resolved, thresholds, _c = sprite_example
    t, verdicts = _evaluate_sigil_dag(
        thresholds, depends_on="tabard", parent_severity=Severity.required
    )
    assert verdicts["sigil"].zone is Zone.NA  # gated by its parent, not refused by the guard
    assert t.overall is Zone.FAIL


# --------------------------------------------------------------------------------------------
# F-a6acaab1 -- the wave-2 em-dash sweep (F-fd21bd37) covered --help pages and errors.py's
# DEFAULT_HINTS. It did not cover the RUNTIME output surface, and the string it missed is on
# the hottest non-bind path in the product: build_checkpoint composes the escalation text with
# a literal U+2014, that text becomes ContrastiveCheckpoint.text -> OrchestrationResult.reason,
# and the CLI prints it verbatim.
#
# Measured before the fix under PYTHONIOENCODING=cp437:strict: an escalating mock run died with
# an unhandled UnicodeEncodeError inside click after writing the first banner line, so on a
# cp437 console every escalation reported error[RUNTIME_UNEXPECTED] at exit 2 and the operator
# never saw the contrastive checkpoint at all -- the UNCERTAINTY_GATED_HUMANS artifact is
# exactly what the crash destroys.
#
# The instances are fixed in checkpoint.py, exit_contract.py and family_guard.py. The CLASS is
# closed by the sweep at the bottom: which text is user-facing is not a stable property of
# where that text sits, so every string literal in the domain that is not a docstring is held
# to ASCII. Docstrings and comments are excluded deliberately and the exclusion is paid for:
# nothing in this domain prints them (`pcraft schema` dumps Contract.model_json_schema() only,
# which reaches core/contract, not here) -- pinned by the last test in this section.
# --------------------------------------------------------------------------------------------

_CONSOLE_ENCODING = "cp437"

_DOMAIN_SOURCE_GLOBS = (
    "core/gate/*.py",
    "core/loop/*.py",
    "core/receipt/*.py",
    "errors.py",
    "gate_report.py",
)


def _domain_sources() -> list[Path]:
    import pcraft

    root = Path(pcraft.__file__).parent
    found: list[Path] = []
    for pattern in _DOMAIN_SOURCE_GLOBS:
        found.extend(sorted(root.glob(pattern)))
    assert found, "domain globs matched nothing; the fixture is broken, not the code"
    return found


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """id() of every str Constant that is a bare expression statement.

    That is exactly the docstring set: module / class / function docstrings, plus the
    attribute-docstring convention LoopConfig.thresholds_version uses. Comments never reach
    the AST at all, so they need no exclusion.
    """
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def _printable_literals(path: Path) -> list[tuple[int, str]]:
    """(lineno, text) for every non-docstring str literal, f-string fragments included.

    f-string fragments matter: checkpoint.py's em dash lived inside
    ``f"{line.thought}; {line.chose} - {line.claim}."``, which is a JoinedStr, not a plain
    Constant, and is invisible to a scan that only looks at whole string literals.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_constant_ids(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _flagged_transcript(overall: Zone) -> GateTranscript:
    """One FAIL and one could-not-confirm atom, so every per-line branch of _line() is used and
    ``parts.extend(...)`` -- the line that carried the em dash -- actually runs."""
    return GateTranscript(
        contract_id="test:pin-a6acaab1",
        overall=overall,
        verdicts=[
            _one_atom_verdict(atom_id="face", score=0.05, zone=Zone.FAIL),
            _one_atom_verdict(
                atom_id="palette", score=0.55, zone=Zone.UNCERTAIN, tier_used=1,
            ),
            _one_atom_verdict(
                atom_id="weapon", score=None, zone=Zone.SKIPPED, tier_used=None,
                tiers_consulted=[], verifier_id=None, reason="no verifier available for tier",
            ),
        ],
        tier_census=TierCensus(required=[0, 1], executed=[0, 1]),
    )


@pytest.mark.parametrize(
    "overall", [Zone.UNCERTAIN, Zone.FAIL, Zone.UNAVAILABLE, Zone.NA],
    ids=["uncertain", "fail", "unavailable", "other"],
)
def test_the_contrastive_checkpoint_text_prints_on_a_cp437_console(overall):
    """All four overall-Zone branches of build_checkpoint, because the em dash was not in any
    of them -- it was in the per-line join every branch shares, which is worse: no branch was
    safe. ASCII rather than merely cp437-encodable, for the reason the DEFAULT_HINTS pin
    already gives: ASCII is the only codepage-independent guarantee and this is advice, not
    typography."""
    checkpoint = build_checkpoint(_flagged_transcript(overall))
    assert checkpoint.lines, "no flagged lines means the join under test never ran"
    checkpoint.text.encode("ascii")
    checkpoint.text.encode(_CONSOLE_ENCODING, errors="strict")


def test_the_escalation_reason_the_cli_prints_survives_cp437(tmp_path):
    """End to end through the real loop, on the failure run_mock_loop's own docstring names as
    the example. OrchestrationResult.reason IS checkpoint.text on this path, and the CLI writes
    it verbatim -- so this is the exact string that crashed click."""
    from pcraft.sample import run_mock_loop

    result = run_mock_loop(records_dir=str(tmp_path), verifier_scores={"face": 0.1})
    assert result.decision == "escalated"
    assert result.checkpoint is not None
    assert result.reason == result.checkpoint.text
    result.reason.encode(_CONSOLE_ENCODING, errors="strict")


def test_every_printable_string_literal_in_this_domain_encodes_on_a_cp437_console():
    """The class, not the three instances. A refusal or a checkpoint is worth nothing if
    PRINTING it raises, and the em dash reached the console from three different kinds of site:
    an f-string fragment (checkpoint.py), a ``hint=`` argument (exit_contract.py) and a
    ``message`` argument (family_guard.py). None of those is a DEFAULT_HINTS entry, which is
    all the wave-2 sweep looked at."""
    offenders: list[str] = []
    for path in _domain_sources():
        for lineno, text in _printable_literals(path):
            try:
                text.encode(_CONSOLE_ENCODING, errors="strict")
            except UnicodeEncodeError as err:
                bad = text[err.start : err.end]
                offenders.append(f"{path.name}:{lineno}: {bad!r} (U+{ord(bad[0]):04X})")
    assert not offenders, (
        "string literals a cp437 console cannot print:\n" + "\n".join(offenders)
    )


def test_every_printable_string_literal_in_this_domain_is_pure_ascii():
    """One notch stricter than cp437, same argument as the DEFAULT_HINTS pin: cp437 accepts a
    handful of accented characters that then break on a UTF-8-only reader, and no message in
    this domain needs one."""
    offenders: list[str] = []
    for path in _domain_sources():
        for lineno, text in _printable_literals(path):
            bad = sorted({f"U+{ord(c):04X}" for c in text if ord(c) > 127})
            if bad:
                offenders.append(f"{path.name}:{lineno}: {', '.join(bad)}")
    assert not offenders, "non-ASCII string literals in this domain:\n" + "\n".join(offenders)


def test_no_docstring_in_this_domain_reaches_a_printed_surface():
    """What the sweep's docstring exclusion is paid for with.

    core/contract holds its whole FILE to ASCII because pydantic folds each model's docstring
    into `model_json_schema()` and `pcraft schema` prints that. Nothing in this domain is
    dumped that way, so its docstrings are not user-facing text and the sweep above may
    legitimately skip them. This test is what goes red the day that stops being true.
    """
    import pcraft

    root = Path(pcraft.__file__).parent
    dumpers = sorted(
        {
            p.relative_to(root).as_posix()
            for p in root.rglob("*.py")
            for line in p.read_text(encoding="utf-8").splitlines()
            if "model_json_schema" in line and not line.lstrip().startswith("#")
        }
    )
    assert dumpers == ["core/contract/schema.py"], (
        f"a new schema-dump site would put docstrings on a printed surface: {dumpers}"
    )


# --------------------------------------------------------------------------------------------
# F-09f30018 -- three guards in this domain do not say whether they are reachable through a
# shipped path today. The repo already treats that as required: F-c1832100 corrected
# retry_policy.verdict_from_transcript for exactly this, and exit_contract's census branch
# states plainly "Not reachable via harness.evaluate() today". A guard that does not say reads
# as either dead code (delete it) or a live check (rely on it) -- and a maintainer cannot tell
# which without re-deriving the whole call graph.
# --------------------------------------------------------------------------------------------


def test_the_dangling_parent_branch_states_that_it_is_defence_in_depth():
    """The loader's _reject_unknown_depends_on refuses this input at resolve() time, so the
    SKIPPED branch is not reachable through any shipped command -- the same status
    exit_contract's census branch declares one file over. The branch's long CORRECTED IN PLACE
    comment described the old measured consequence and never said that."""
    src = inspect.getsource(harness.evaluate)
    assert "defence in depth" in src, (
        "the SKIPPED branch must say whether a shipped path can reach it, like its siblings do"
    )
    assert "_reject_unknown_depends_on" in src, "name the guard that makes it unreachable"


def test_the_cycle_guard_states_whether_a_shipped_path_reaches_it():
    """Same rule applied to the guard this wave adds, rather than leaving the next reader to
    ask the same question about a fourth branch."""
    src = inspect.getsource(harness.evaluate)
    assert "topological" in src, "the guard is on the topological() call"
    assert "constructs a QuestionDAG" in src or "builds a QuestionDAG" in src, (
        "say who can still reach a cyclic DAG once the loader refuses one"
    )


# --------------------------------------------------------------------------------------------
# F-56203d3d (the report half) -- format_transcript printed atom ids ONLY, so `palette` and
# `no_rival_colours` appeared without their claims, even though build_checkpoint one file over
# does print them and `pcraft gate` compiles the DAG (cli/__init__.py:376) and drops it before
# calling format_transcript at :381. The renderer is given the optional argument here; wiring the
# CLI's two call sites to pass it is a cli/** edit and belongs to that domain.
# --------------------------------------------------------------------------------------------


def _failing_transcript(resolved, thresholds):
    from pcraft.testing import passing_verifiers

    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", passing_verifiers(scores={"palette": 0.333}), thresholds,
        generator_family="stable-diffusion",
    )
    return dag, t


def test_format_transcript_can_render_the_claim_behind_a_problem_atom(sprite_example):
    from pcraft.gate_report import format_transcript

    _s, resolved, thresholds, _c = sprite_example
    dag, t = _failing_transcript(resolved, thresholds)
    claim = dag.by_id("palette").text
    assert claim, "the example's palette atom has a claim; the fixture is the thing under test"

    without = format_transcript(t)
    assert claim not in without, "today's rendering is the red case, not a pre-existing pass"

    with_dag = format_transcript(t, dag=dag)
    assert claim in with_dag, "an atom id is not a claim"


def test_the_claim_is_rendered_only_for_the_atoms_that_need_reading(sprite_example):
    """A wall of claims under every PASS row is the 'wall of green' this module's docstring
    refuses. Only the problem atoms carry one."""
    from pcraft.gate_report import format_transcript

    _s, resolved, thresholds, _c = sprite_example
    dag, t = _failing_transcript(resolved, thresholds)
    text = format_transcript(t, dag=dag)
    assert dag.by_id("palette").text in text
    assert dag.by_id("no_shield").text not in text, "no_shield passed; it needs no claim"


def test_format_transcript_without_a_dag_is_byte_for_byte_what_it_was(sprite_example):
    """The argument is optional and additive -- both shipped call sites pass one argument."""
    from pcraft.gate_report import format_transcript

    _s, resolved, thresholds, _c = sprite_example
    _dag, t = _failing_transcript(resolved, thresholds)
    assert format_transcript(t) == format_transcript(t, dag=None)
