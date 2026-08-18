"""The synth -> generate -> verify -> retry -> bind state machine.

This is the whole loop, domain-agnostic. It is driven by the AMEND/ADVANCE verdict machine and
obeys every standard: it binds ONLY after every required atom passes AND the tier census confirms
the gate actually ran (ANDON); it runs a no-skip compensator check before any irreversible action
(NAMED_COMPENSATORS); the gate is a different family from the generator (EXTERNAL_VERIFIER, via
family_guard); and every bound asset writes a replayable receipt (PIN_PER_STEP).

⚑ CORRECTED IN PLACE (F-04533cc6): this docstring used to also claim "UNCERTAIN routes to a human
(UNCERTAINTY_GATED_HUMANS)". It does not. verdict_from_transcript maps Zone.UNCERTAIN to
Verdict.AMEND — the identical verdict Zone.FAIL gets — so an uncertain required atom is fed
straight into the same repair ladder as a confirmed failure (choose_repair treats
failed_required() and uncertain_required() as one combined list). A human is reached only once the
repair budget is exhausted: gated on step count (repairs_left), not on uncertainty itself, which
is precisely the anti-pattern UNCERTAINTY_GATED_HUMANS defines itself against. This is not a
silent pass — the andon invariant above still holds, nothing binds without ADVANCE — but it is not
UNCERTAINTY_GATED_HUMANS either. STANDARDS.md already scores this standard an honest 2 with a
remediation note; this wave corrects the claim, not the escalation policy itself.

A TRANSIENT generator error (timeout / rate limit / GPU OOM, i.e. an uncoded exception or a coded
one outside the SYNTH_/CONTRACT_/GATE_/INPUT_ prefixes) is auto-retried within the existing
best-of-N / repair budget; a SEMANTIC one escalates immediately — never an automatic re-roll
(retry_policy.classify_failure).

The contract is used TWICE here: ``synthesize`` covers its atoms, and ``compile_questions`` gates the
same atoms — one declarative source, two consumers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ...errors import PromptCraftError, wrap_error
from ..contract.compile_questions import compile_questions
from ..contract.hash import contract_hash
from ..contract.schema import ResolvedContract
from ..gate import harness
from ..gate.preflight import preflight_image
from ..gate.family_guard import assert_distinct_families
from ..gate.thresholds import ThresholdTable, Zone
from ..gate.verifier_iface import Verifier, forbid_clipscore
from ..receipt.asset_record import AssetRecord, persist
from ..synth.assert_ import assert_coverage
from ..synth.synthesizer_iface import Synthesizer, SynthResult
from ..synth.visual_inventory import assert_tokens_trace
from .compensators import CompensatorRegistry, default_registry
from .generator_iface import GenerationResult, Generator
from .retry_policy import (
    OutcomeClass,
    RepairAction,
    RetryBudget,
    Verdict,
    choose_repair,
    classify_failure,
    verdict_from_transcript,
)


class LoopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encoder_rules: str = ""
    thresholds_version: str = "unversioned"
    records_dir: str = "records"
    base_seed: int = 1000
    max_resynth: int = 3  # coverage-assert backtrack cap
    budget: RetryBudget = RetryBudget()


class Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt: int
    seed: int
    overall: Zone
    verdict: Verdict
    repair: RepairAction | None = None
    note: str = ""


class OrchestrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # F-a250372c: narrowed from a bare `str` (comment used to also list "blocked", which no
    # assignment site ever produced — see retry_policy.Verdict's docstring for why BLOCK was
    # removed rather than wired). Every one of the four call sites below already only ever used
    # these two values; the Literal just makes that statically enforced.
    decision: Literal["bound", "escalated"]
    reason: str
    attempts: list[Attempt]
    record: AssetRecord | None = None


class _GenerationBlocked(Exception):
    """Internal control-flow signal only: generator.generate() raised a SEMANTIC error
    (F-83c3ad00). Raised by ``_safe_generate``, caught in ``run()``, never escapes this module.

    A SEMANTIC defect is human-gated and must not be absorbed into best-of-N / the repair
    ladder's automatic reroll. A TRANSIENT error never reaches this class at all — ``_safe_generate``
    resolves it internally by returning ``None`` so the caller's existing loop naturally retries
    within its existing budget, no extra budget granted."""

    def __init__(self, err: PromptCraftError) -> None:
        super().__init__(str(err))
        self.err = err


def run(
    resolved: ResolvedContract,
    synthesizer: Synthesizer,
    generator: Generator,
    verifiers: dict[int, Verifier],
    thresholds: ThresholdTable,
    *,
    config: LoopConfig | None = None,
    compensators: CompensatorRegistry | None = None,
) -> OrchestrationResult:
    config = config or LoopConfig()
    compensators = compensators or default_registry()
    budget = config.budget.model_copy()
    attempts: list[Attempt] = []

    # --- EXTERNAL_VERIFIER discipline: the gate must be a different family + no banned metric.
    for v in verifiers.values():
        forbid_clipscore(v)
    assert_distinct_families(generator.family, [v.family for v in verifiers.values()])

    # --- SYNTHESIZE with pre-gen coverage Assert (backtrack on miss) + anti-prose-dump guard.
    synth = _synthesize_with_assert(resolved, synthesizer, config)
    if synth is None:
        return OrchestrationResult(
            decision="escalated", reason="synthesizer could not cover every required atom",
            attempts=attempts,
        )
    try:
        assert_tokens_trace(synth.prompt, synth.visual_inventory)
    except PromptCraftError as err:
        # a prose-dump is a SEMANTIC synth defect -> human-gated, never an auto-reroll
        compensators.require("escalation-ticket")
        return OrchestrationResult(decision="escalated", reason=err.to_safe_text(), attempts=attempts)

    # --- The contract, used the SECOND time: derive the gate's question DAG from the same atoms.
    dag = compile_questions(resolved)
    conditioning = _assemble_conditioning(resolved)

    # --- GENERATE + VERIFY: bounded best-of-N, then the DAG-keyed repair ladder.
    try:
        chosen = _best_of_n(resolved, synth, generator, verifiers, thresholds, dag, conditioning, config, attempts, budget)
        chosen = _repair_ladder(resolved, synth, generator, verifiers, thresholds, dag, conditioning, attempts, budget, chosen)
    except _GenerationBlocked as blocked:
        # F-83c3ad00: a SEMANTIC generate() failure -- human-gated, never an automatic re-roll.
        # Mirrors the prose-dump SEMANTIC synth defect above: no gen/transcript pair ever existed
        # to build a record from, so there is nothing to persist and no "records-write" door to
        # guard here -- only the human-notice compensator, exactly like that other early-return.
        compensators.require("escalation-ticket")
        return OrchestrationResult(decision="escalated", reason=blocked.err.to_safe_text(), attempts=attempts)

    gen, transcript = chosen
    verdict = verdict_from_transcript(transcript)

    # --- DECIDE. Bind only on ADVANCE (every required atom PASS AND a complete tier census).
    if verdict is Verdict.ADVANCE:
        compensators.require("records-write")
        compensators.require("bind-to-canon")  # no-skip gate BEFORE the irreversible action
        record = _build_record(resolved, synth, gen, transcript, thresholds, dag, len(attempts), "bound")
        persist(record, config.records_dir)
        return OrchestrationResult(decision="bound", reason="all required atoms passed", attempts=attempts, record=record)

    # FAIL / UNCERTAIN after the budget -> human checkpoint (uncertainty / retry-exhaustion).
    # ⚑ CORRECTED IN PLACE (F-b269af73): this persist() call is structurally identical to the
    # bound path's persist() above and was missing its "records-write" no-skip check -- only
    # "escalation-ticket" ran before it. A caller-supplied registry that named "escalation-ticket"
    # but not "records-write" let this write through unguarded. Both doors now require both.
    compensators.require("records-write")
    compensators.require("escalation-ticket")
    record = _build_record(resolved, synth, gen, transcript, thresholds, dag, len(attempts), "escalated")
    persist(record, config.records_dir)
    reason = (
        f"gate overall={transcript.overall.value} after {len(attempts)} attempts; "
        f"required failures={[v.atom_id for v in transcript.failed_required()]}, "
        f"unconfirmed={[v.atom_id for v in transcript.uncertain_required()]}"
    )
    return OrchestrationResult(decision="escalated", reason=reason, attempts=attempts, record=record)


# --------------------------------------------------------------------------- helpers


def _synthesize_with_assert(resolved, synthesizer, config) -> SynthResult | None:
    last: PromptCraftError | None = None
    for _ in range(config.max_resynth):
        synth = synthesizer.synthesize(resolved, config.encoder_rules)
        try:
            assert_coverage(resolved, synth.atom_coverage)
            return synth
        except PromptCraftError as err:
            last = err  # backtrack: re-synthesize (a real LM gets the missing-atom list injected)
    del last
    return None


def _assemble_conditioning(resolved: ResolvedContract, identity_weight_bump: float = 0.0) -> dict:
    cond: dict = {
        "identity_refs": [ir.model_dump() for ir in resolved.identity_refs],
        "pose_refs": [a.spatial.ref for a in resolved.must_have if a.spatial and a.spatial.kind.value == "pose"],
    }
    if identity_weight_bump:
        cond["identity_weight_bump"] = identity_weight_bump
    return cond


def _safe_generate(
    generator: Generator, prompt: str, negative_prompt: str, conditioning: dict, seed: int
) -> GenerationResult | None:
    """Call generator.generate(), classifying any raised error per the TRANSIENT/SEMANTIC split
    retry_policy documents (F-83c3ad00). A bare exception is wrapped first
    (``RUNTIME_GENERATE_FAILED`` carries none of classify_failure's semantic prefixes, so it reads
    as TRANSIENT -- the same bucket a raw timeout/network error belongs in) so an uncoded crash is
    treated the same as a coded one. TRANSIENT returns None so the caller's own retry loop
    (best-of-N or the repair ladder) naturally moves on within its existing budget -- no extra
    budget is granted. SEMANTIC raises _GenerationBlocked so run() escalates immediately: never an
    automatic re-roll for a semantic defect."""
    try:
        return generator.generate(prompt, negative_prompt, conditioning, seed)
    except Exception as err:  # classified immediately below; never silently swallowed
        wrapped = wrap_error(err, "RUNTIME_GENERATE_FAILED")
        if classify_failure(wrapped.code) is OutcomeClass.SEMANTIC:
            raise _GenerationBlocked(wrapped) from wrapped
        return None


def _gate(gen: GenerationResult, verifiers, thresholds, dag, generator_family: str):
    try:
        preflight_image(gen.image_path)
    except PromptCraftError as err:
        # IO_GATE_INPUT used to escape run() as a raw coded error outside the
        # TRANSIENT/SEMANTIC envelope. Could-not-see-the-image is not a generate
        # retry; escalate like any other SEMANTIC block.
        raise _GenerationBlocked(err) from err
    # Coordinated signature change (wave-2 core-gate sibling, F-461c4198): the family guard now
    # also runs inside harness.evaluate itself. generator_family is the orchestrator's own
    # trusted generator.family -- already validated once by assert_distinct_families in run()
    # before any generation happened -- not gen.generator_family (a field the generator
    # self-reports on its own result). Threading the already-validated value keeps one source of
    # truth instead of trusting the generator's echo of it a second time.
    return harness.evaluate(dag, gen.image_path, verifiers, thresholds, generator_family=generator_family)


def _best_of_n(resolved, synth, generator, verifiers, thresholds, dag, conditioning, config, attempts, budget):
    candidates: list[tuple[GenerationResult, harness.GateTranscript]] = []
    n = max(1, budget.best_of_n)
    for i in range(n):
        seed = config.base_seed + i
        gen = _safe_generate(generator, synth.prompt, synth.negative_prompt, conditioning, seed)
        if gen is None:
            continue  # TRANSIENT generate() failure -- auto-retry with the next seed, same budget
        transcript = _gate(gen, verifiers, thresholds, dag, generator.family)
        attempts.append(Attempt(attempt=len(attempts) + 1, seed=seed, overall=transcript.overall,
                                verdict=verdict_from_transcript(transcript), note="best-of-N"))
        candidates.append((gen, transcript))
        if transcript.overall is Zone.PASS:  # early exit on first clean pass
            break
    budget.rerolls = max(0, budget.rerolls - len(candidates))
    if not candidates:
        # every attempt in the loop above was a TRANSIENT generate() failure -- the auto-retry
        # budget (best-of-N) is now exhausted with nothing to gate. Escalate rather than hand
        # _select_best an empty list.
        raise _GenerationBlocked(PromptCraftError(
            "RUNTIME_GENERATE_EXHAUSTED",
            f"every best-of-{n} generate() attempt raised a transient error; none produced an image",
        ))
    return _select_best(candidates)


def _select_best(candidates):
    # The VERIFIER is the selector: prefer PASS, then fewest required failures, then most passes.
    def key(item):
        _gen, t = item
        rank = {Zone.PASS: 0, Zone.UNCERTAIN: 1, Zone.FAIL: 2, Zone.UNAVAILABLE: 3}.get(
            t.overall, 4
        )
        n_fail = len(t.failed_required())
        n_pass = sum(1 for v in t.verdicts if v.zone is Zone.PASS)
        return (rank, n_fail, -n_pass)

    return min(candidates, key=key)


def _repair_ladder(resolved, synth, generator, verifiers, thresholds, dag, conditioning, attempts, budget, chosen):
    gen, transcript = chosen
    bump = 0.0
    # Hard cap guarantees termination even if one repair action keeps being chosen (e.g. an identity
    # atom that never recovers): cap = total remaining repair budget, then escalate to a human.
    repairs_left = budget.inpaints + budget.reprompts + budget.rerolls
    while transcript.overall is not Zone.PASS and repairs_left > 0:
        repairs_left -= 1
        repair = choose_repair(transcript, budget, dag)
        seed = gen.seed
        cond = conditioning
        if repair is RepairAction.STRENGTHEN_IDENTITY:
            bump += 0.15
            cond = _assemble_conditioning(resolved, identity_weight_bump=bump)
            seed = gen.seed + 100
            budget.rerolls -= 1
        elif repair is RepairAction.REROLL_NEW_SEED:
            seed = gen.seed + 100
            budget.rerolls -= 1
        elif repair is RepairAction.RESYNTH_REWEIGHT:
            seed = gen.seed + 1
            budget.reprompts -= 1
        elif repair is RepairAction.INPAINT_REGION:
            # Regional inpaint is not implemented on the shipped generators.
            # Same seed + same prompt is a byte-identical regenerate. Vary the
            # seed so the named action is not a no-op until a real inpaint exists.
            seed = gen.seed + 10
            budget.inpaints -= 1

        new_gen = _safe_generate(generator, synth.prompt, synth.negative_prompt, cond, seed)
        if new_gen is None:
            continue  # TRANSIENT generate() failure on this repair attempt -- repairs_left and
                      # the action's own sub-budget above are already charged; try the next one
        new_t = _gate(new_gen, verifiers, thresholds, dag, generator.family)
        attempts.append(Attempt(attempt=len(attempts) + 1, seed=seed, overall=new_t.overall,
                                verdict=verdict_from_transcript(new_t), repair=repair, note="repair"))
        # keep the better of old/new (the verifier is still the selector)
        gen, transcript = _select_best([(gen, transcript), (new_gen, new_t)])
    return gen, transcript


def _build_record(resolved, synth, gen, transcript, thresholds, dag, retry_count, decision) -> AssetRecord:
    verifier_ids = sorted({v.verifier_id for v in transcript.verdicts if v.verifier_id})
    return AssetRecord(
        record_id=f"{resolved.id.replace(':', '_')}-seed{gen.seed}",
        contract_id=resolved.id,
        contract_hash=contract_hash(resolved),
        compiled_synth_id=synth.backend,
        synth_backend=synth.backend,
        synth_degraded=synth.degraded,
        generator_id=gen.generator_id,
        generator_family=gen.generator_family,
        seed=gen.seed,
        sampler=gen.sampler,
        conditioning=gen.conditioning,
        verifier_ids=verifier_ids,
        thresholds_version=thresholds.version,
        question_dag=dag,
        gate_transcript=transcript,
        retry_count=retry_count,
        decision=decision,
    )
