"""The synth -> generate -> verify -> retry -> bind state machine.

This is the whole loop, domain-agnostic. It is driven by the BLOCK/AMEND/VERIFY/ADVANCE verdict
machine and obeys every standard: it binds ONLY after every required atom passes (ANDON); it runs a
no-skip compensator check before any irreversible action (NAMED_COMPENSATORS); the gate is a
different family from the generator (EXTERNAL_VERIFIER, via family_guard); UNCERTAIN routes to a
human (UNCERTAINTY_GATED_HUMANS); and every bound asset writes a replayable receipt (PIN_PER_STEP).

The contract is used TWICE here: ``synthesize`` covers its atoms, and ``compile_questions`` gates the
same atoms — one declarative source, two consumers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ...errors import PromptCraftError
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
from .retry_policy import RepairAction, RetryBudget, Verdict, choose_repair, verdict_from_transcript


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
    decision: str  # bound | escalated | blocked
    reason: str
    attempts: list[Attempt]
    record: AssetRecord | None = None


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
    chosen = _best_of_n(resolved, synth, generator, verifiers, thresholds, dag, conditioning, config, attempts, budget)
    chosen = _repair_ladder(resolved, synth, generator, verifiers, thresholds, dag, conditioning, attempts, budget, chosen)

    gen, transcript = chosen
    verdict = verdict_from_transcript(transcript)

    # --- DECIDE. Bind only on ADVANCE (every required atom PASS).
    if verdict is Verdict.ADVANCE:
        compensators.require("records-write")
        compensators.require("bind-to-canon")  # no-skip gate BEFORE the irreversible action
        record = _build_record(resolved, synth, gen, transcript, thresholds, dag, len(attempts), "bound")
        persist(record, config.records_dir)
        return OrchestrationResult(decision="bound", reason="all required atoms passed", attempts=attempts, record=record)

    # FAIL / UNCERTAIN after the budget -> human checkpoint (uncertainty / retry-exhaustion).
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


def _gate(gen: GenerationResult, verifiers, thresholds, dag):
    preflight_image(gen.image_path)
    return harness.evaluate(dag, gen.image_path, verifiers, thresholds)


def _best_of_n(resolved, synth, generator, verifiers, thresholds, dag, conditioning, config, attempts, budget):
    candidates: list[tuple[GenerationResult, harness.GateTranscript]] = []
    for i in range(max(1, budget.best_of_n)):
        seed = config.base_seed + i
        gen = generator.generate(synth.prompt, synth.negative_prompt, conditioning, seed)
        transcript = _gate(gen, verifiers, thresholds, dag)
        attempts.append(Attempt(attempt=len(attempts) + 1, seed=seed, overall=transcript.overall,
                                verdict=verdict_from_transcript(transcript), note="best-of-N"))
        candidates.append((gen, transcript))
        if transcript.overall is Zone.PASS:  # early exit on first clean pass
            break
    budget.rerolls = max(0, budget.rerolls - len(candidates))
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
            budget.inpaints -= 1  # same seed (regional inpaint)

        new_gen = generator.generate(synth.prompt, synth.negative_prompt, cond, seed)
        new_t = _gate(new_gen, verifiers, thresholds, dag)
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
