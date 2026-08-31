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
from pcraft.core.loop.retry_policy import Verdict, is_unrepairable, verdict_from_transcript
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


def test_inpaint_repair_keeps_the_seed_and_names_the_region(tmp_path):
    """INPAINT_REGION is a real inpaint: same seed, mask is the variation.

    The stub writes stub_seed{N}_inpaint.png so the named action is not a
    byte-identical regenerate. choose_repair still picks INPAINT for a lone leaf.
    """
    from pcraft.core.loop.retry_policy import RepairAction, choose_repair

    result = _run(tmp_path, verifier_scores={"weapon": 0.05})
    inpaint_attempts = [a for a in result.attempts if a.repair is RepairAction.INPAINT_REGION]
    if not inpaint_attempts:
        dag = __import__("pcraft.core.contract.compile_questions", fromlist=["compile_questions"]).compile_questions
        _s, resolved, _t, _c = load_sprite_example()
        compiled = dag(resolved)
        from pcraft.core.loop.retry_policy import RetryBudget
        t = GateTranscript(
            contract_id=resolved.id,
            overall=Zone.FAIL,
            verdicts=[
                AtomVerdict(
                    atom_id="weapon", polarity=Polarity.affirm, severity=Severity.required,
                    score=0.05, zone=Zone.FAIL, tier_used=1, verifier_id="v", reason="x",
                )
            ],
            tier_census=TierCensus(required=[0, 1], executed=[0, 1]),
        )
        assert choose_repair(t, RetryBudget(), compiled) is RepairAction.INPAINT_REGION
        return
    first_seed = result.attempts[0].seed
    assert any(a.seed == first_seed for a in inpaint_attempts)
    inpaint_pngs = list((tmp_path / "_stub_images").glob("stub_seed*_inpaint.png"))
    assert inpaint_pngs, "INPAINT_REGION must write a distinct file, not reuse stub_seed{N}.png"


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
    base = {"atom_id": "a", "polarity": Polarity.affirm, "severity": Severity.required,
                "score": 0.9, "zone": Zone.PASS, "tier_used": 1, "verifier_id": "v", "reason": "x"}
    base.update(over)
    return AtomVerdict(**base)


def test_verdict_from_transcript_requires_a_complete_tier_census():
    """A PASS whose tier census shows a required tier never executed must not ADVANCE.

    Corrected with F-c1832100: this docstring used to call that "the GATE-002 scenario" and
    describe a fallback verifier scoring an atom on a tier the census does not credit. That
    mechanism was removed by F-175c3b3e -- harness._pick no longer falls forward -- and the
    identifier GATE-002 resolves nowhere in the repo. The transcript below is therefore built by
    hand, not produced by evaluate(): the census is an INDEPENDENT net underneath the Zone
    roll-up, deliberately kept so a future routing change cannot make a short census invisible
    again. Before the census check existed, verdict_from_transcript read only `overall` and
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


# --------------------------------------------------------------------------- F-LOOP-FEAT-004 skip the ladder when the gate could not run


def test_unavailable_gate_does_not_burn_the_repair_ladder(tmp_path):
    """Every required atom SKIPPED / overall UNAVAILABLE: another seed will not help."""
    result = _run(tmp_path, verifier_scores=lambda _q: None)
    assert result.decision == "escalated"
    assert result.attempts, "best-of-N still ran"
    assert all(a.repair is None for a in result.attempts)
    assert all(a.note == "best-of-N" for a in result.attempts)


def test_incomplete_census_does_not_burn_the_repair_ladder(tmp_path):
    """Only Tier-1 registered: some atoms score, a required tier never ran. Unrepairable."""
    from pcraft.sample import load_sprite_example
    from pcraft.testing import ScriptedVerifier, StubGenerator

    _store, resolved, thresholds, compiled = load_sprite_example()
    synth = TemplateSynthesizer(compiled)
    gen = StubGenerator(out_dir=tmp_path / "_stub_images")
    # lone Tier-1: palette/siglip2 atoms SKIP, vqa atoms score, census 1 of 2
    verifiers = {1: ScriptedVerifier({"face": 0.05})}
    result = orchestrate.run(
        resolved, synth, gen, verifiers, thresholds,
        config=LoopConfig(thresholds_version=thresholds.version, records_dir=str(tmp_path)),
    )
    assert result.decision == "escalated"
    assert all(a.repair is None for a in result.attempts)


# --------------------------------------------------------------------------- real RESYNTH (not a seed bump)


class _PromptSpy:
    def __init__(self, inner: StubGenerator):
        self.inner = inner
        self.prompts: list[str] = []
        self.generator_id = inner.generator_id
        self.family = inner.family

    def generate(self, prompt, negative_prompt, conditioning, seed):
        self.prompts.append(prompt)
        return self.inner.generate(prompt, negative_prompt, conditioning, seed)


def test_resynth_front_loads_failed_atoms_instead_of_only_bumping_the_seed(tmp_path):
    """RESYNTH_REWEIGHT used to increment the seed and reuse the same prompt.

    Two leaf fails (weapon + skin) pick RESYNTH. The next generate must lead
    with those claims, not just a different seed.
    """
    from pcraft.core.loop.retry_policy import RepairAction

    spy = _PromptSpy(StubGenerator(out_dir=tmp_path / "_stub_images"))
    result = _run(tmp_path, verifier_scores={"weapon": 0.05, "skin": 0.05}, generator=spy)
    resynths = [a for a in result.attempts if a.repair is RepairAction.RESYNTH_REWEIGHT]
    assert resynths, f"expected a RESYNTH, got {[a.repair for a in result.attempts]}"
    assert len(spy.prompts) >= 2
    later = spy.prompts[-1]
    weapon_at = later.lower().find("battle-axe")
    skin_at = later.lower().find("grey-green")
    tabard_at = later.lower().find("tabard")
    assert weapon_at != -1 and skin_at != -1
    assert min(weapon_at, skin_at) < tabard_at


def test_a_scored_fail_with_a_complete_census_still_repairs(tmp_path):
    """The other half: a real FAIL on a fully-run gate still climbs the ladder."""
    result = _run(tmp_path, verifier_scores={"face": 0.05})
    assert result.decision == "escalated"
    assert any(a.repair for a in result.attempts)


def test_is_unrepairable_names_the_three_unrepairable_shapes():
    skipped = _atom_verdict(score=None, zone=Zone.SKIPPED, tier_used=None, verifier_id=None)
    unavailable = GateTranscript(
        contract_id="c", overall=Zone.UNAVAILABLE, verdicts=[skipped],
        tier_census=TierCensus(required=[1], executed=[]),
    )
    short = GateTranscript(
        contract_id="c", overall=Zone.UNCERTAIN, verdicts=[_atom_verdict()],
        tier_census=TierCensus(required=[0, 1], executed=[1]),
    )
    scored_fail = GateTranscript(
        contract_id="c", overall=Zone.FAIL,
        verdicts=[_atom_verdict(score=0.05, zone=Zone.FAIL)],
        tier_census=TierCensus(required=[1], executed=[1]),
    )
    assert is_unrepairable(unavailable) is True
    assert is_unrepairable(short) is True
    assert is_unrepairable(scored_fail) is False


def test_bare_exception_from_generate_is_treated_as_transient(tmp_path):
    """An un-coded exception (a raw timeout/network error, not a hand-rolled PromptCraftError) is
    exactly the case the retry_policy docstring names ("generate error / timeout") and must also
    auto-retry, not crash -- proves _safe_generate's wrap_error step, not just its PromptCraftError
    fast path."""
    gen = _AlwaysRaisesGenerator(lambda: TimeoutError("connection timed out"))
    result = _run(tmp_path, generator=gen)
    assert result.decision == "escalated"
    assert gen.calls == 4


# --------------------------------------------------------------------------- F-badd2eba


def _run_with_config(tmp_path, config, *, generator=None):
    _store, resolved, thresholds, compiled = load_sprite_example()
    synth = TemplateSynthesizer(compiled)
    gen = generator or StubGenerator(out_dir=tmp_path / "_stub_images")
    return orchestrate.run(
        resolved, synth, gen, passing_verifiers(), thresholds, config=config,
    )


def test_a_thresholds_version_that_disagrees_with_the_table_is_refused(tmp_path):
    """F-badd2eba: LoopConfig.thresholds_version was declared, set by both public entry points and
    four test files, and read by nothing -- grep across src/ found exactly one occurrence, the
    field declaration itself. _build_record stamps the receipt from the ThresholdTable argument,
    not from config, so a caller who set LoopConfig(thresholds_version='my.table.v2') against a
    differently-versioned table got no error and no effect: a knob that looked live and was inert.

    It is an assertion hook now. Setting it states which table you believe you are running, and
    the loop refuses to run against a different one -- the replay-drift check applied at bind
    time rather than only at replay time."""
    _store, _resolved, thresholds, _compiled = load_sprite_example()
    gen = _AlwaysRaisesGenerator(lambda: AssertionError("generate must not be reached"))
    with pytest.raises(PromptCraftError) as exc:
        _run_with_config(
            tmp_path,
            LoopConfig(thresholds_version="my.table.v2", records_dir=str(tmp_path)),
            generator=gen,
        )
    assert exc.value.code == "CONFIG_THRESHOLDS_INVALID"
    assert "my.table.v2" in str(exc.value)
    assert thresholds.version in str(exc.value)
    assert gen.calls == 0, "the refusal must land before any pixels are generated"


def test_a_matching_thresholds_version_still_binds(tmp_path):
    """Positive control: the hook must not break the callers that already set the field. Both
    public entry points (sample.run_mock_loop / run_live_loop) pass table.version, which matches,
    so every existing call site stays valid."""
    _store, _resolved, thresholds, _compiled = load_sprite_example()
    result = _run_with_config(
        tmp_path, LoopConfig(thresholds_version=thresholds.version, records_dir=str(tmp_path))
    )
    assert result.decision == "bound"
    assert result.record.thresholds_version == thresholds.version


def test_an_unset_thresholds_version_asserts_nothing(tmp_path):
    """The other half of the hook: not setting it is not a claim, so it must not refuse. A
    default that asserted would turn the field from inert into a trap for every caller who never
    set it."""
    result = _run_with_config(tmp_path, LoopConfig(records_dir=str(tmp_path)))
    assert result.decision == "bound"
    assert LoopConfig().thresholds_version == "", "unset must be falsy, or the hook fires by default"


# --------------------------------------------------------------------------- F-9ee95e14


def test_a_failed_generate_records_an_attempt_row_naming_the_code(tmp_path):
    """F-9ee95e14: every TRANSIENT generate() failure was discarded whole -- code, message, hint
    and cause chain -- and no Attempt row was recorded. `_safe_generate` returned None and the
    caller's `if gen is None: continue` appended nothing, so a generator that failed four times
    produced `attempts=[]` and `retry_count=0`.

    asset_record documents that list as BOTH the audit trail and the offline optimizer's
    training set, so systematically omitting the runs that went wrong is the one omission it
    cannot afford. A failed generate is a real attempt and is recorded as one."""
    gen = _AlwaysRaisesGenerator(lambda: PromptCraftError("RUNTIME_TIMEOUT", "generator timed out"))
    result = _run(tmp_path, generator=gen)
    assert result.decision == "escalated"
    assert gen.calls == 4
    assert len(result.attempts) == 4, "one row per failed generate; this used to be zero"
    assert [a.attempt for a in result.attempts] == [1, 2, 3, 4]
    assert [a.seed for a in result.attempts] == [1000, 1001, 1002, 1003]
    assert all("RUNTIME_TIMEOUT" in a.note for a in result.attempts), (
        "the note has to name the code that actually failed, or the row is another dead end"
    )
    assert all(a.overall is Zone.UNAVAILABLE for a in result.attempts)
    assert all(a.verdict is Verdict.AMEND for a in result.attempts)


def test_the_exhaustion_error_names_the_underlying_failure(tmp_path):
    """RUNTIME_GENERATE_EXHAUSTED was raised with no cause and had no DEFAULT_HINTS entry, so the
    escalation reason read "every best-of-4 generate() attempt raised a transient error; none
    produced an image" -- naming nothing. The CLI then wraps that in GATE_UNAVAILABLE, whose hint
    says "Check the generator/verifier the reason names", and the reason named nothing."""
    gen = _AlwaysRaisesGenerator(lambda: PromptCraftError("RUNTIME_TIMEOUT", "generator timed out"))
    result = _run(tmp_path, generator=gen)
    assert "RUNTIME_GENERATE_EXHAUSTED" in result.reason
    assert "RUNTIME_TIMEOUT" in result.reason, "the exhaustion must name the real failure"
    assert "hint:" in result.reason, "a code with no hint is a diagnostic dead end"


def test_the_exhaustion_error_chains_the_last_failure_as_its_cause(tmp_path):
    """The structured half of the same fix: the last error is chained with `cause=`, so
    `to_debug_text()` recovers the original traceback instead of ending at the exhaustion.

    Driven through `_best_of_n` directly because `run()` converts the raised error into an
    OrchestrationResult and only the safe text survives -- the chain is on the exception, which
    is the object that has to carry it."""
    from pcraft.core.contract.compile_questions import compile_questions
    from pcraft.core.loop.retry_policy import RetryBudget

    _store, resolved, thresholds, compiled = load_sprite_example()
    synth_result = TemplateSynthesizer(compiled).synthesize(resolved, "")
    gen = _AlwaysRaisesGenerator(lambda: PromptCraftError("RUNTIME_TIMEOUT", "generator timed out"))
    attempts, budget = [], RetryBudget()
    with pytest.raises(orchestrate._GenerationBlockedError) as exc:
        orchestrate._best_of_n(
            resolved, synth_result, gen, passing_verifiers(), thresholds,
            compile_questions(resolved), {}, LoopConfig(records_dir=str(tmp_path)),
            attempts, budget,
        )
    err = exc.value.err
    assert err.code == "RUNTIME_GENERATE_EXHAUSTED"
    assert isinstance(err.cause, PromptCraftError)
    assert err.cause.code == "RUNTIME_TIMEOUT"
    assert "RUNTIME_TIMEOUT" in err.to_debug_text()
    assert len(attempts) == 4, "the rows are appended to the caller's list, not lost with the error"


def test_a_missing_dependency_is_not_retried_and_keeps_its_own_hint(tmp_path):
    """Part 4 of F-9ee95e14: re-attempting a missing dependency N times cannot succeed. DEP_ codes
    carried none of classify_failure's semantic prefixes, so DEP_IMAGE_MISSING classified TRANSIENT
    and was re-rolled four times -- and for a real generator each retry re-attempts a model load.

    Its own hint ("Install the GPU extra...") was then destroyed on the exact path where it is the
    answer. Classified non-retryable, the coded error escalates on the first raise and reaches the
    caller intact, hint included."""
    gen = _AlwaysRaisesGenerator(lambda: PromptCraftError("DEP_IMAGE_MISSING", "torch is not installed"))
    result = _run(tmp_path, generator=gen)
    assert result.decision == "escalated"
    assert gen.calls == 1, "a missing dependency is not a seed problem; retrying it is pure waste"
    assert "DEP_IMAGE_MISSING" in result.reason
    assert "pip install" in result.reason, "the code's own actionable hint must survive"


def test_a_generator_that_cannot_load_is_not_retried(tmp_path):
    """Same class, different code: RUNTIME_GENERATOR_LOAD_FAILED is what sdxl_generator and
    flux_generator raise when the checkpoint will not load. A second seed does not fix a
    checkpoint, so it is non-retryable by name rather than by prefix -- RUNTIME_ as a whole stays
    transient, which is what keeps a plain timeout auto-retrying."""
    gen = _AlwaysRaisesGenerator(
        lambda: PromptCraftError("RUNTIME_GENERATOR_LOAD_FAILED", "checkpoint missing")
    )
    result = _run(tmp_path, generator=gen)
    assert result.decision == "escalated"
    assert gen.calls == 1
    assert "RUNTIME_GENERATOR_LOAD_FAILED" in result.reason


def test_classify_failure_keeps_the_transient_semantic_split():
    """The split itself is not being widened away. Only two things move to non-retryable, and the
    codes that make best-of-N worth having stay transient."""
    from pcraft.core.loop.retry_policy import OutcomeClass, classify_failure

    assert classify_failure("RUNTIME_TIMEOUT") is OutcomeClass.TRANSIENT
    assert classify_failure("RUNTIME_GENERATE_FAILED") is OutcomeClass.TRANSIENT
    assert classify_failure("IO_GATE_INPUT") is OutcomeClass.TRANSIENT
    assert classify_failure("DEP_IMAGE_MISSING") is OutcomeClass.SEMANTIC
    assert classify_failure("DEP_SYNTH_MISSING") is OutcomeClass.SEMANTIC
    assert classify_failure("RUNTIME_GENERATOR_LOAD_FAILED") is OutcomeClass.SEMANTIC
    assert classify_failure("CONTRACT_RELAXATION") is OutcomeClass.SEMANTIC
    assert classify_failure("GATE_FAIL") is OutcomeClass.SEMANTIC


# --------------------------------------------------------------------------- F-c1832100


def test_the_census_gate_does_not_advertise_a_retracted_mechanism():
    """F-c1832100: verdict_from_transcript justified the census gate with a "Reachable example"
    naming harness._pick falling forward to a different tier's verifier -- a mechanism
    F-175c3b3e REMOVED. _pick is now `return (verifiers[want], want) if want in verifiers else
    (None, None)` and carries its own note saying a missing tier is SKIPPED.

    Two files in this one domain then said opposite things about the same scenario, both citing
    the same fix id: exit_contract.error_from_transcript's census branch states plainly "Not
    reachable via harness.evaluate() today". The cited identifier GATE-002 resolved nowhere in
    the repo except that docstring and the test that copied it.

    The gate itself is right and stays. Only the stale claim goes -- a maintainer trusting it
    would either reintroduce cross-tier fallback or delete the census gate as dead code, and a
    stale claim living in src/ is the exact defect class this package exists to catch."""
    from pathlib import Path

    from pcraft.core.loop import retry_policy

    src = Path(retry_policy.__file__).read_text(encoding="utf-8")
    assert "Reachable example" not in src, (
        "the scenario is not reachable through harness.evaluate() today; exit_contract.py says so"
    )
    assert "GATE-002" not in src, "GATE-002 resolves nowhere in this repo; drop it or define it"
    # and the gate it justifies is still wired -- the correction is to the prose, not the check
    assert "census" in src
