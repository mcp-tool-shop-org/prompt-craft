"""Regression tests for the wave-2 core-loop amend pass.

Each test names the finding it pins and, for the behavioral fixes, is written to fail against the
pre-fix code for the stated reason (see the wave-2 dispatch / out-core-loop.json for the
before/after story). Everything here is GPU-free: StubGenerator/ScriptedVerifier only.

Covers:
  F-b269af73  the compensator no-skip gate must guard BOTH persist() doors, not just the bound one
  (tier census) verdict_from_transcript must consult the tier census, not just Zone
  F-a250372c  Verdict is now a real two-member enum (BLOCK/VERIFY removed, not dead-and-unused)
  F-04533cc6  Zone.UNCERTAIN gets the identical verdict Zone.FAIL gets (pins the corrected docstring)
  F-83c3ad00  a generate() error is classified TRANSIENT (auto-retry) vs SEMANTIC (escalate now)
"""

from __future__ import annotations

import pytest

from pcraft.core.contract.compile_questions import Polarity
from pcraft.core.contract.schema import Severity
from pcraft.core.gate.harness import AtomVerdict, GateTranscript, TierCensus
from pcraft.core.gate.thresholds import Zone
from pcraft.core.loop import orchestrate
from pcraft.core.loop.compensators import Compensator, CompensatorRegistry
from pcraft.core.loop.orchestrate import LoopConfig
from pcraft.core.loop.retry_policy import Verdict, verdict_from_transcript
from pcraft.core.synth.signature import TemplateSynthesizer
from pcraft.errors import PromptCraftError
from pcraft.sample import load_sprite_example
from pcraft.testing import StubGenerator, passing_verifiers


def _run(tmp_path, *, verifier_scores=None, generator=None, compensators=None):
    """Run the real sprite example through orchestrate.run() with GPU-free stubs -- the same
    wiring pcraft.sample.run_mock_loop uses, but exposing `generator=`/`compensators=` overrides
    that run_mock_loop does not, since this domain's fixes need both."""
    _store, resolved, thresholds, compiled = load_sprite_example()
    synth = TemplateSynthesizer(compiled)
    gen = generator or StubGenerator(out_dir=tmp_path / "_stub_images")
    verifiers = passing_verifiers(scores=verifier_scores)
    config = LoopConfig(thresholds_version=thresholds.version, records_dir=str(tmp_path))
    return orchestrate.run(
        resolved, synth, gen, verifiers, thresholds, config=config, compensators=compensators,
    )


def test_default_run_actually_binds(tmp_path):
    """LOOP-W3-001: the helper must reach ADVANCE, or the bound-door test is false-green."""
    result = _run(tmp_path)
    assert result.decision == "bound"


# --------------------------------------------------------------------------- F-b269af73


def _registry_missing_records_write() -> CompensatorRegistry:
    """Every OTHER runtime compensator, deliberately missing "records-write" -- the exact gap
    F-b269af73 describes: a caller-supplied registry that never named that specific undo."""
    reg = CompensatorRegistry()
    noop = lambda *_a, **_k: None  # noqa: E731
    reg.register(Compensator("bind-to-canon", noop, "test", "n/a"))
    reg.register(Compensator("escalation-ticket", noop, "test", "n/a"))
    return reg


def test_bound_door_refuses_to_persist_without_records_write(tmp_path):
    """The ADVANCE/bound persist() door already required "records-write" before this wave --
    this pins that it still does, so fixing the OTHER door can't regress this one."""
    with pytest.raises(PromptCraftError) as exc:
        _run(tmp_path, compensators=_registry_missing_records_write())
    assert exc.value.code == "STATE_NO_COMPENSATOR"


def test_escalation_door_refuses_to_persist_without_records_write(tmp_path):
    """F-b269af73: the escalation persist() door -- reached once the repair budget exhausts on a
    failed required atom -- must ALSO require "records-write" before persisting, exactly like the
    bound door. Before the fix, a registry with "escalation-ticket" but not "records-write" let
    this second, structurally identical persist() call through unguarded."""
    with pytest.raises(PromptCraftError) as exc:
        _run(tmp_path, verifier_scores={"face": 0.05}, compensators=_registry_missing_records_write())
    assert exc.value.code == "STATE_NO_COMPENSATOR"


# --------------------------------------------------------------------------- tier census


def _atom_verdict(**over) -> AtomVerdict:
    base = dict(atom_id="a", polarity=Polarity.affirm, severity=Severity.required,
                score=0.9, zone=Zone.PASS, tier_used=1, verifier_id="v", reason="x")
    base.update(over)
    return AtomVerdict(**base)


def test_verdict_from_transcript_requires_a_complete_tier_census():
    """A PASS whose tier census shows a required tier never executed must not ADVANCE. This is
    the GATE-002 scenario: a fallback verifier scored the atom on a tier the census doesn't
    credit toward its own home tier, Zone rolls up to PASS, but the gate never actually ran on
    the tier the atom required. Before the fix, verdict_from_transcript read only `overall` and
    would ADVANCE (and bind) on this transcript."""
    transcript = GateTranscript(
        contract_id="c", overall=Zone.PASS, verdicts=[_atom_verdict()],
        tier_census=TierCensus(required=[0], executed=[]),  # n=0 < m=1
    )
    assert verdict_from_transcript(transcript) is Verdict.AMEND


def test_verdict_from_transcript_advances_on_a_complete_census():
    """Positive control: PASS + a fully-executed census still ADVANCEs. Zone and the census are
    two separate facts (per the dispatch); this proves the census check is additive, not a
    replacement for the Zone.PASS requirement."""
    transcript = GateTranscript(
        contract_id="c", overall=Zone.PASS, verdicts=[_atom_verdict()],
        tier_census=TierCensus(required=[1], executed=[1]),  # n=1 == m=1
    )
    assert verdict_from_transcript(transcript) is Verdict.ADVANCE


def test_an_incomplete_census_does_not_advance_even_with_no_scored_atoms():
    """Edge of the same fix: Zone.UNAVAILABLE (could_not_run) must not ADVANCE either -- unaffected
    by the census check since overall is not PASS, but pinned here so the two independent gates
    (Zone, census) are both exercised by name rather than assumed from the PASS case alone."""
    transcript = GateTranscript(
        contract_id="c", overall=Zone.UNAVAILABLE,
        verdicts=[_atom_verdict(score=None, zone=Zone.SKIPPED, tier_used=None, verifier_id=None)],
        tier_census=TierCensus(required=[1], executed=[]),
    )
    assert verdict_from_transcript(transcript) is Verdict.AMEND


# --------------------------------------------------------------------------- F-a250372c


def test_verdict_enum_has_no_unconstructed_members():
    """F-a250372c: BLOCK and VERIFY were defined but never constructed or compared anywhere in
    the domain (confirmed by repo-wide grep during triage). Removed rather than left advertising
    a halt path that could never fire -- see retry_policy.Verdict's docstring for the reasoning."""
    assert {m.value for m in Verdict} == {"AMEND", "ADVANCE"}


# --------------------------------------------------------------------------- F-04533cc6


def test_uncertain_zone_gets_the_same_verdict_as_fail():
    """F-04533cc6: the module docstring previously overclaimed "UNCERTAIN routes to a human
    (UNCERTAINTY_GATED_HUMANS)". It does not -- UNCERTAIN maps to AMEND, identically to FAIL, and
    a human is only reached once the repair budget is exhausted (a step count). This pins the
    actual mapping the corrected docstring now describes, so the two can't silently drift apart
    again."""
    fail_t = GateTranscript(
        contract_id="c", overall=Zone.FAIL, verdicts=[_atom_verdict(score=0.01, zone=Zone.FAIL)],
        tier_census=TierCensus(required=[1], executed=[1]),
    )
    uncertain_t = GateTranscript(
        contract_id="c", overall=Zone.UNCERTAIN,
        verdicts=[_atom_verdict(score=0.5, zone=Zone.UNCERTAIN)],
        tier_census=TierCensus(required=[1], executed=[1]),
    )
    assert verdict_from_transcript(fail_t) is Verdict.AMEND
    assert verdict_from_transcript(uncertain_t) is Verdict.AMEND


# --------------------------------------------------------------------------- F-83c3ad00


class _AlwaysRaisesGenerator:
    """Generator double whose generate() always raises -- proves the TRANSIENT/SEMANTIC wiring
    without any GPU dependency. `family` normalizes to "stable-diffusion" like StubGenerator, so
    the EXTERNAL_VERIFIER family guard in run() (line ~124) passes before generation is ever
    attempted."""

    generator_id = "test.raiser.v0"
    family = "stable-diffusion"

    def __init__(self, make_error):
        self._make_error = make_error
        self.calls = 0

    def generate(self, prompt, negative_prompt, conditioning, seed):
        self.calls += 1
        raise self._make_error()


def test_transient_generate_error_auto_retries_within_budget(tmp_path):
    """F-83c3ad00: a TRANSIENT generate() error (an uncoded exception, or any code outside
    SYNTH_/CONTRACT_/GATE_/INPUT_) must not crash run() -- it auto-retries within the existing
    best-of-N budget, never an extra one. Before the fix this propagated straight out of run()
    and crashed the whole orchestration -- classify_failure/OutcomeClass were dead code."""
    gen = _AlwaysRaisesGenerator(lambda: PromptCraftError("RUNTIME_TIMEOUT", "generator timed out"))
    result = _run(tmp_path, generator=gen)
    assert result.decision == "escalated"
    assert gen.calls == 4  # LoopConfig's default RetryBudget.best_of_n -- no more, no fewer


def test_semantic_generate_error_escalates_without_reroll(tmp_path):
    """F-83c3ad00: a SEMANTIC generate() error (a coded CONTRACT_/SYNTH_/GATE_/INPUT_ defect) is
    human-gated immediately -- it must NOT be absorbed into the best-of-N reroll loop the way a
    TRANSIENT error is."""
    gen = _AlwaysRaisesGenerator(
        lambda: PromptCraftError("CONTRACT_RELAXATION", "generator refused the contract")
    )
    result = _run(tmp_path, generator=gen)
    assert result.decision == "escalated"
    assert gen.calls == 1  # never re-rolled -- a semantic defect is not retried


def test_bare_exception_from_generate_is_treated_as_transient(tmp_path):
    """An un-coded exception (a raw timeout/network error, not a hand-rolled PromptCraftError) is
    exactly the case the retry_policy docstring names ("generate error / timeout") and must also
    auto-retry, not crash -- proves _safe_generate's wrap_error step, not just its PromptCraftError
    fast path."""
    gen = _AlwaysRaisesGenerator(lambda: TimeoutError("connection timed out"))
    result = _run(tmp_path, generator=gen)
    assert result.decision == "escalated"
    assert gen.calls == 4
