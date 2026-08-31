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
is precisely the anti-pattern UNCERTAINTY_GATED_HUMANS defines itself against. Escalation
still happens after the budget. The contrastive checkpoint is the human artifact at that
door (STANDARDS #5). Nothing binds without ADVANCE.

A TRANSIENT generator error (timeout / rate limit / GPU OOM, i.e. an uncoded exception or a coded
one outside the SYNTH_/CONTRACT_/GATE_/INPUT_/DEP_ prefixes and not RUNTIME_GENERATOR_LOAD_FAILED)
is auto-retried within the existing best-of-N / repair budget; a SEMANTIC one escalates immediately
-- never an automatic re-roll (retry_policy.classify_failure). Every failed generate still records
an Attempt row naming its code -- TRANSIENT and SEMANTIC alike -- and the exhaustion error quotes
and chains the last failure, so a permanently broken generator is not reported as a transient
exhaustion that names nothing.

CORRECTED IN PLACE (F-521335b9): the sentence above used to end at "naming its code", and that was
true of the TRANSIENT path only. On the SEMANTIC path ``_safe_generate`` raised, ``run()`` returned
early with ``attempts`` untouched, and no row was ever appended for a generate() that was actually
called and actually failed -- so ``pcraft bind`` printed "attempts: 0" for a run in which the
generator had been invoked once and raised. The two codes that recorded nothing were DEP_ and
RUNTIME_GENERATOR_LOAD_FAILED, i.e. including DEP_IMAGE_MISSING, the code the fix that widened the
SEMANTIC bucket was itself measured on. The row is recorded at the raise site now (see
``_generate_and_record``), which is what makes the sentence true rather than narrower.

The contract is used TWICE here: ``synthesize`` covers its atoms, and ``compile_questions`` gates the
same atoms — one declarative source, two consumers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ...errors import PromptCraftError, wrap_error
from ..contract.compile_questions import compile_questions
from ..contract.hash import contract_hash
from ..contract.schema import ResolvedContract
from ..gate import harness
from ..gate.checkpoint import ContrastiveCheckpoint, build_checkpoint
from ..gate.family_guard import assert_distinct_families
from ..gate.preflight import preflight_image
from ..gate.thresholds import ThresholdTable, Zone
from ..gate.verifier_iface import Verifier, forbid_clipscore
from ..receipt.asset_record import AssetRecord, persist
from ..synth.assert_ import assert_coverage
from ..synth.synthesizer_iface import Synthesizer, SynthResult
from ..synth.visual_inventory import assert_tokens_trace
from .compensators import CompensatorRegistry, default_registry
from .generator_iface import GenerationResult, Generator
from .retry_policy import (
    Attempt,
    OutcomeClass,
    RepairAction,
    RetryBudget,
    Verdict,
    choose_repair,
    classify_failure,
    is_unrepairable,
    verdict_from_transcript,
)


class LoopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encoder_rules: str = ""
    thresholds_version: str = ""
    """The threshold table version the caller believes it is running. Empty means "no claim".

    CORRECTED IN PLACE (F-badd2eba). Nothing read this field: grep across ``src/`` found
    exactly one occurrence, the declaration. ``_build_record`` stamps the receipt from the
    ``ThresholdTable`` argument's own ``version``, not from here -- which is the RIGHT thing to
    stamp, so no receipt ever carried wrong data. The defect was that the knob looked live:
    both public entry points set it, four test files set it, and a caller who set it to a
    version the table did not have got no error and no effect.

    ``run()`` now asserts it. Setting it is a statement about which table you are running, and
    a table that disagrees is refused (``CONFIG_THRESHOLDS_VERSION_MISMATCH``) -- the
    replay-drift check ``asset_record.replay`` performs after the fact, applied at bind time
    instead. The default changed from ``"unversioned"`` to ``""`` so that "unset" is falsy and
    therefore asserts nothing; a sentinel string would have made the hook fire for every caller
    who never set it.

    REACHABILITY (F-09f30018): this is a LIBRARY-caller guard and cannot fire through any
    shipped CLI command. Both public entry points -- ``sample.run_mock_loop`` and
    ``sample.run_live_loop`` -- pass ``table.version`` from the same ``load_workspace()`` call
    that produced the table, so their claim agrees by construction; ``LoopConfig()`` is
    constructed nowhere else in ``src/``; and an unset field is falsy, so it asserts nothing.
    That is intended, not a gap. It is stated because the repo made stating it the norm one
    file over (``retry_policy.verdict_from_transcript``, F-c1832100): a guard that does not say
    whether a shipped path reaches it reads as either dead code to delete or a live check to
    rely on, and a reader cannot tell which.
    """
    records_dir: str = "records"
    base_seed: int = 1000
    max_resynth: int = 3  # coverage-assert backtrack cap
    budget: RetryBudget = RetryBudget()


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
    checkpoint: ContrastiveCheckpoint | None = None


class _GenerationBlockedError(Exception):
    """Internal control-flow signal only: this run is human-gated and must not be re-rolled
    (F-83c3ad00). Caught in ``run()``, never escapes this module.

    Three sites raise it, which matters because only one of them owes an Attempt row:
    ``_safe_generate`` on a SEMANTIC generate() failure (a row IS owed -- generate() was called
    and failed; see ``_generate_and_record``), ``_gate`` when preflight cannot read the image
    that generate() successfully produced (no row: nothing about the generate failed), and
    ``_best_of_n`` on RUNTIME_GENERATE_EXHAUSTED after every attempt has already recorded its
    own row (no row: appending here would report N+1 attempts for N generates).

    A SEMANTIC defect must not be absorbed into best-of-N / the repair ladder's automatic
    reroll. A TRANSIENT error never reaches this class at all -- ``_safe_generate`` returns
    ``(None, err)`` so the caller's existing loop naturally retries within its existing budget,
    no extra budget granted, and hands back the classified error so the caller can record it.

    CORRECTED IN PLACE (F-521335b9). This docstring said ``_safe_generate`` "resolves it
    internally by returning ``None``" -- a return shape that stopped existing when F-9ee95e14
    changed it to the ``(None, err)`` tuple, and the whole point of that change was that the
    error stopped being discarded. It also described SEMANTIC as covering only "schema-invalid
    output" after the same commit moved DEP_ and RUNTIME_GENERATOR_LOAD_FAILED into the bucket
    (retry_policy._SEMANTIC_PREFIXES / _SEMANTIC_CODES)."""

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

    # --- CONFIG: the caller's threshold-version claim, if it made one, must be the table it got.
    # F-badd2eba: this field was inert. Asserting it here refuses a run whose table is not the one
    # the caller believes it is running, BEFORE any pixels are generated -- the same drift check
    # `asset_record.replay` applies to a finished receipt, moved to the door. Reachable only from
    # a library caller, never from the CLI -- see LoopConfig.thresholds_version's REACHABILITY
    # note for why, and why saying so is required here.
    #
    # F-09f30018: this used to raise CONFIG_THRESHOLDS_INVALID, which thresholds.load_thresholds
    # already raises for a structurally malformed band table. One covered, machine-parseable code
    # carrying two unrelated meanings is exactly what STABILITY.md's "parse the code, not the
    # prose" contract forbids -- and DEFAULT_HINTS described only the other one, so a script
    # could not tell them apart and a human got the wrong advice.
    if config.thresholds_version and config.thresholds_version != thresholds.version:
        raise PromptCraftError(
            "CONFIG_THRESHOLDS_VERSION_MISMATCH",
            f"config.thresholds_version is {config.thresholds_version!r} but the threshold table "
            f"passed to run() is {thresholds.version!r}; the receipt would be stamped "
            f"{thresholds.version!r}, so the same scores would land in a different zone from the "
            f"table you named",
            hint="Pass the version of the table you are actually running (table.version), or "
            "leave config.thresholds_version unset to assert nothing.",
        )

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
        chosen = _repair_ladder(
            resolved, synth, synthesizer, generator, verifiers, thresholds, dag,
            conditioning, attempts, budget, chosen, config,
        )
    except _GenerationBlockedError as blocked:
        # F-83c3ad00: a SEMANTIC generate() failure -- human-gated, never an automatic re-roll.
        # Mirrors the prose-dump SEMANTIC synth defect above: no gen/transcript pair ever existed
        # to build a record from, so there is nothing to persist and no "records-write" door to
        # guard here -- only the human-notice compensator, exactly like that other early-return.
        compensators.require("escalation-ticket")
        return OrchestrationResult(decision="escalated", reason=blocked.err.to_safe_text(), attempts=attempts)

    # F-f99c78f8: the THIRD element is the SynthResult that produced this image, not the one
    # ``_synthesize_with_assert`` returned at the top. The repair ladder can re-synthesize
    # (RESYNTH_REWEIGHT) and ``_select_best`` can then keep either candidate, so stamping the
    # receipt from the original ``synth`` would have written a prompt that did not produce the
    # pixels the receipt certifies -- a field that is wrong is worse than a field that is absent.
    gen, transcript, chosen_synth = chosen
    verdict = verdict_from_transcript(transcript)

    # --- DECIDE. Bind only on ADVANCE (every required atom PASS AND a complete tier census).
    if verdict is Verdict.ADVANCE:
        compensators.require("records-write")
        compensators.require("bind-to-canon")  # no-skip gate BEFORE the irreversible action
        record = _build_record(
            resolved, chosen_synth, gen, transcript, thresholds, dag, len(attempts), "bound",
            attempts=attempts, synthesizer=synthesizer,
        )
        persist(record, config.records_dir)
        return OrchestrationResult(decision="bound", reason="all required atoms passed", attempts=attempts, record=record)

    # FAIL / UNCERTAIN after the budget -> human checkpoint (uncertainty / retry-exhaustion).
    # ⚑ CORRECTED IN PLACE (F-b269af73): this persist() call is structurally identical to the
    # bound path's persist() above and was missing its "records-write" no-skip check -- only
    # "escalation-ticket" ran before it. A caller-supplied registry that named "escalation-ticket"
    # but not "records-write" let this write through unguarded. Both doors now require both.
    compensators.require("records-write")
    compensators.require("escalation-ticket")
    checkpoint = build_checkpoint(transcript, dag)
    record = _build_record(
        resolved, chosen_synth, gen, transcript, thresholds, dag, len(attempts), "escalated",
        attempts=attempts, checkpoint=checkpoint, synthesizer=synthesizer,
    )
    persist(record, config.records_dir)
    reason = checkpoint.text
    return OrchestrationResult(
        decision="escalated",
        reason=reason,
        attempts=attempts,
        record=record,
        checkpoint=checkpoint,
    )


# --------------------------------------------------------------------------- helpers


def _synthesize_with_assert(resolved, synthesizer, config) -> SynthResult | None:
    last: PromptCraftError | None = None
    for _ in range(config.max_resynth):
        synth = synthesizer.synthesize(resolved, config.encoder_rules)
        try:
            assert_coverage(resolved, synth.atom_coverage)
        except PromptCraftError as err:
            last = err  # backtrack: re-synthesize (a real LM gets the missing-atom list injected)
        else:
            return synth
    del last
    return None


def _resynth_reweight(
    synthesizer, resolved, encoder_rules: str, failed_ids: list[str], previous: SynthResult
) -> SynthResult:
    """Re-synthesize with failed atoms front-loaded. A seed bump is not this.

    TemplateSynthesizer accepts ``boost_ids``. A synthesizer that does not is
    still called again; the prompt is then reordered so failed tokens lead.
    A broken resynth keeps the previous prompt rather than crashing the loop.
    """
    try:
        try:
            result = synthesizer.synthesize(resolved, encoder_rules, boost_ids=failed_ids)
        except TypeError:
            result = synthesizer.synthesize(resolved, encoder_rules)
            result = _front_load_failed(result, failed_ids)
        assert_coverage(resolved, result.atom_coverage)
        assert_tokens_trace(result.prompt, result.visual_inventory)
    except PromptCraftError:
        return previous
    else:
        return result


def _front_load_failed(synth: SynthResult, failed_ids: list[str]) -> SynthResult:
    """Fallback when the synthesizer cannot accept boost_ids: reorder the prompt."""
    boost = set(failed_ids)
    rows = list(synth.visual_inventory)
    for row in rows:
        if row.atom_id in boost:
            row.front_load_rank -= 1000
    depictable = sorted((r for r in rows if r.depictable), key=lambda r: r.front_load_rank)
    from ..synth.visual_inventory import RENDER_BOILERPLATE

    prompt = ", ".join([r.token for r in depictable] + RENDER_BOILERPLATE)
    return synth.model_copy(update={"prompt": prompt, "visual_inventory": rows})


def _inpaint_region(dag, transcript) -> str:
    failed = transcript.failed_required() or transcript.uncertain_required()
    if not failed:
        return "center"
    question = dag.by_id(failed[0].atom_id)
    if question is not None and question.spatial is not None and question.spatial.kind.value == "region":
        return question.spatial.ref
    return failed[0].atom_id


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
) -> tuple[GenerationResult | None, PromptCraftError | None]:
    """Call generator.generate(), classifying any raised error per the TRANSIENT/SEMANTIC split
    retry_policy documents (F-83c3ad00). A bare exception is wrapped first
    (``RUNTIME_GENERATE_FAILED`` carries none of classify_failure's semantic prefixes, so it reads
    as TRANSIENT -- the same bucket a raw timeout/network error belongs in) so an uncoded crash is
    treated the same as a coded one. TRANSIENT returns ``(None, err)`` so the caller's own retry
    loop (best-of-N or the repair ladder) naturally moves on within its existing budget -- no extra
    budget is granted. SEMANTIC raises _GenerationBlockedError so run() escalates immediately: never
    an automatic re-roll for a non-retryable defect.

    CORRECTED IN PLACE (F-9ee95e14). This returned a bare ``None`` on the TRANSIENT path and the
    classified error was discarded whole -- code, message, hint and cause chain. Both callers then
    did ``continue`` and appended no Attempt, so a permanently broken generator was reported as a
    transient exhaustion that named nothing, and the receipt's attempts list systematically omitted
    exactly the runs that went wrong. The error is now handed back so the caller can record it.
    """
    try:
        return generator.generate(prompt, negative_prompt, conditioning, seed), None
    except Exception as err:  # noqa: BLE001 - classified immediately below, never swallowed
        wrapped = wrap_error(err, "RUNTIME_GENERATE_FAILED")
        if classify_failure(wrapped.code) is OutcomeClass.SEMANTIC:
            raise _GenerationBlockedError(wrapped) from wrapped
        return None, wrapped


def _generate_and_record(
    generator: Generator, prompt: str, negative_prompt: str, conditioning: dict, seed: int,
    attempts: list[Attempt], repair=None,
) -> tuple[GenerationResult | None, PromptCraftError | None]:
    """``_safe_generate`` plus the Attempt row a failed generate owes the receipt (F-521335b9).

    Both failure classes record here, which is what makes orchestrate's module docstring true:
    a TRANSIENT failure returns ``(None, err)`` and the caller retries within its own budget; a
    SEMANTIC one raises past this function to ``run()``, but the row is appended on the way out.

    Recording in ``run()``'s ``except _GenerationBlockedError`` handler instead would be wrong
    in both directions: that handler is also reached by the preflight failure (where generate()
    SUCCEEDED, so "generate failed" would be a false row) and by RUNTIME_GENERATE_EXHAUSTED
    (where N rows already exist, so it would double-count the last one). The fact "generate()
    was called and failed" is only true here, so this is where it is written down.
    """
    try:
        gen, err = _safe_generate(generator, prompt, negative_prompt, conditioning, seed)
    except _GenerationBlockedError as blocked:
        attempts.append(_failed_generate_attempt(attempts, seed, blocked.err, repair=repair))
        raise
    if gen is None:
        attempts.append(_failed_generate_attempt(attempts, seed, err, repair=repair))
    return gen, err


def _failed_generate_attempt(attempts, seed: int, err: PromptCraftError | None, repair=None) -> Attempt:
    """One Attempt row for a generate that never produced an image (F-9ee95e14).

    ``overall`` is UNAVAILABLE because nothing was gated -- the same Zone the roll-up uses for
    "no required atom produced a score" -- and the verdict is AMEND, since a failed generate is
    never an ADVANCE. The code goes in ``note`` so the receipt names the real failure rather than
    recording a gap where an attempt happened."""
    return Attempt(
        attempt=len(attempts) + 1,
        seed=seed,
        overall=Zone.UNAVAILABLE,
        verdict=Verdict.AMEND,
        repair=repair,
        note=f"generate failed [{err.code}]" if err is not None else "generate failed",
    )


def _gate(gen: GenerationResult, verifiers, thresholds, dag, generator_family: str):
    try:
        preflight_image(gen.image_path)
    except PromptCraftError as err:
        # IO_GATE_INPUT used to escape run() as a raw coded error outside the
        # TRANSIENT/SEMANTIC envelope. Could-not-see-the-image is not a generate
        # retry; escalate like any other SEMANTIC block.
        raise _GenerationBlockedError(err) from err
    # Coordinated signature change (wave-2 core-gate sibling, F-461c4198): the family guard now
    # also runs inside harness.evaluate itself. generator_family is the orchestrator's own
    # trusted generator.family -- already validated once by assert_distinct_families in run()
    # before any generation happened -- not gen.generator_family (a field the generator
    # self-reports on its own result). Threading the already-validated value keeps one source of
    # truth instead of trusting the generator's echo of it a second time.
    return harness.evaluate(dag, gen.image_path, verifiers, thresholds, generator_family=generator_family)


def _best_of_n(resolved, synth, generator, verifiers, thresholds, dag, conditioning, config, attempts, budget):
    # (generation, transcript, the SynthResult whose prompt produced it) -- see run()'s unpack.
    candidates: list[tuple[GenerationResult, harness.GateTranscript, SynthResult]] = []
    last_err: PromptCraftError | None = None
    n = max(1, budget.best_of_n)
    for i in range(n):
        seed = config.base_seed + i
        gen, gen_err = _generate_and_record(
            generator, synth.prompt, synth.negative_prompt, conditioning, seed, attempts
        )
        if gen is None:
            # TRANSIENT generate() failure -- auto-retry with the next seed, same budget. The
            # attempt is RECORDED (F-9ee95e14): it happened, it burned a seed, and dropping it
            # made retry_count and the receipt under-report the runs that failed. A SEMANTIC
            # failure never arrives here at all; it raised out of the call above, having
            # recorded its own row on the way (F-521335b9).
            last_err = gen_err
            continue
        transcript = _gate(gen, verifiers, thresholds, dag, generator.family)
        attempts.append(Attempt(attempt=len(attempts) + 1, seed=seed, overall=transcript.overall,
                                verdict=verdict_from_transcript(transcript), note="best-of-N"))
        candidates.append((gen, transcript, synth))
        if transcript.overall is Zone.PASS:  # early exit on first clean pass
            break
    budget.rerolls = max(0, budget.rerolls - len(candidates))
    if not candidates:
        # every attempt in the loop above was a TRANSIENT generate() failure -- the auto-retry
        # budget (best-of-N) is now exhausted with nothing to gate. Escalate rather than hand
        # _select_best an empty list.
        #
        # CORRECTED IN PLACE (F-9ee95e14): this used to be raised with no ``cause=`` and no
        # mention of the code that actually failed, so the escalation reason -- which the CLI
        # surfaces verbatim, then wraps in GATE_UNAVAILABLE whose hint says "check the
        # generator/verifier the reason names" -- named nothing at all. The last failure is now
        # both quoted in the message and chained as the cause, so --debug recovers its traceback.
        message = f"every best-of-{n} generate() attempt raised a transient error; none produced an image"
        if last_err is not None:
            message += f". Last failure: [{last_err.code}] {last_err.message}"
        raise _GenerationBlockedError(PromptCraftError(
            "RUNTIME_GENERATE_EXHAUSTED", message, cause=last_err,
        ))
    return _select_best(candidates)


def _select_best(candidates):
    # The VERIFIER is the selector: prefer PASS, then fewest required failures, then most passes.
    def key(item):
        _gen, t, _synth = item
        rank = {Zone.PASS: 0, Zone.UNCERTAIN: 1, Zone.FAIL: 2, Zone.UNAVAILABLE: 3}.get(
            t.overall, 4
        )
        n_fail = len(t.failed_required())
        n_pass = sum(1 for v in t.verdicts if v.zone is Zone.PASS)
        return (rank, n_fail, -n_pass)

    return min(candidates, key=key)


def _repair_ladder(
    resolved, synth, synthesizer, generator, verifiers, thresholds, dag,
    conditioning, attempts, budget, chosen, config,
):
    gen, transcript, chosen_synth = chosen
    if is_unrepairable(transcript):
        return gen, transcript, chosen_synth
    bump = 0.0
    # ``current_synth`` is the ACTIVE prompt (what the next generate uses); ``chosen_synth`` is
    # the one attached to whichever candidate is currently winning. They diverge the moment a
    # RESYNTH_REWEIGHT lands and _select_best keeps the older image.
    current_synth = chosen_synth
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
            failed_ids = [
                v.atom_id
                for v in (transcript.failed_required() or transcript.uncertain_required())
            ]
            current_synth = _resynth_reweight(
                synthesizer, resolved, config.encoder_rules, failed_ids, current_synth
            )
            seed = gen.seed + 1
            budget.reprompts -= 1
        elif repair is RepairAction.INPAINT_REGION:
            # Same seed: the mask is the variation. The generator sees inpaint_from
            # + inpaint_region and must actually inpaint, not txt2img the same prompt.
            cond = {
                **conditioning,
                "inpaint_from": gen.image_path,
                "inpaint_region": _inpaint_region(dag, transcript),
            }
            budget.inpaints -= 1

        new_gen, _gen_err = _generate_and_record(
            generator, current_synth.prompt, current_synth.negative_prompt, cond, seed,
            attempts, repair=repair,
        )
        if new_gen is None:
            # TRANSIENT generate() failure on this repair attempt -- repairs_left and the action's
            # own sub-budget above are already charged; try the next one. F-9ee95e14: the row is
            # recorded, carrying the repair that was attempted, so the receipt shows a repair that
            # was paid for and never ran instead of showing nothing. F-521335b9: a SEMANTIC
            # failure on a repair records the same row, with the same repair, before it raises.
            continue
        new_t = _gate(new_gen, verifiers, thresholds, dag, generator.family)
        attempts.append(Attempt(attempt=len(attempts) + 1, seed=seed, overall=new_t.overall,
                                verdict=verdict_from_transcript(new_t), repair=repair, note="repair"))
        # keep the better of old/new (the verifier is still the selector), carrying each
        # candidate's own prompt with it so the receipt can name the one that made the pixels
        gen, transcript, chosen_synth = _select_best(
            [(gen, transcript, chosen_synth), (new_gen, new_t, current_synth)]
        )
    return gen, transcript, chosen_synth


def _record_id(resolved, gen, chash: str, created_at: str) -> str:
    """A receipt id that varies per run (F-a99ec99e).

    This was ``f"{resolved.id.replace(':', '_')}-seed{gen.seed}"`` and carried no run identity: no
    time, no contract_hash, no attempt discriminator. ``persist`` derives the filename from it, so
    two runs of one contract targeted one path and the second truncated the first -- and the
    collision was most likely on exactly the runs that matter, since ``base_seed`` defaults to
    1000 and best-of-N early-exits on the first clean PASS. A contract EDIT did not help either:
    contract_hash is stored in the record but was not part of the id, so re-binding after a
    revision overwrote the previous revision's receipt too.

    The hash prefix separates contract revisions; the UTC stamp separates runs of the same
    revision. Microseconds, not seconds: two binds inside one second is an ordinary thing for a
    test or a batch.

    Everything is pushed through ``_fs_safe`` because ``persist`` turns this string into a
    filename. That is not defensive decoration: the first draft of this function spliced in
    ``contract_hash(resolved)[:8]``, which is ``"sha256:a"`` -- the hash is PREFIXED with its
    algorithm -- and on NTFS a colon in a path is not an error, it opens an ALTERNATE DATA STREAM.
    The receipt wrote successfully, ``Path.exists()`` returned True, and the directory listing was
    empty. Caught by ``test_a_second_run_cannot_destroy_the_first_bound_receipt`` counting files
    rather than trusting exists(); the sanitizer is here so the next component with punctuation in
    it cannot repeat it.
    """
    digest = chash.rsplit(":", 1)[-1][:8]
    return _fs_safe(f"{resolved.id}-seed{gen.seed}-{digest}-{created_at}")


def _fs_safe(text: str) -> str:
    """Reduce to characters that are a filename on every platform this ships to."""
    return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in text)


def _build_record(
    resolved, synth, gen, transcript, thresholds, dag, retry_count, decision,
    *, attempts=None, checkpoint=None, synthesizer=None,
) -> AssetRecord:
    verifier_ids = sorted({v.verifier_id for v in transcript.verdicts if v.verifier_id})
    chash = contract_hash(resolved)
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    # F-f99c78f8: compiled_synth_id and synth_backend were assigned the IDENTICAL expression here
    # (both ``synth.backend``), so on the shipped template path both read "template" and the module
    # docstring credited a pinned field carrying no information the field beside it did not. The
    # synthesizer already publishes the id of the artifact it is running --
    # "template.v1+<program_id>@<version>" or "dspy.v1+<artifact_id>" -- which is what
    # "compiled synth id" was always supposed to mean. The backend label stays what it was.
    compiled_synth_id = getattr(synthesizer, "synthesizer_id", "") or synth.backend
    return AssetRecord(
        record_id=_record_id(resolved, gen, chash, stamp),
        contract_id=resolved.id,
        contract_hash=chash,
        compiled_synth_id=compiled_synth_id,
        synth_backend=synth.backend,
        synth_degraded=synth.degraded,
        generator_id=gen.generator_id,
        generator_family=gen.generator_family,
        seed=gen.seed,
        sampler=gen.sampler,
        conditioning=gen.conditioning,
        verifier_ids=verifier_ids,
        thresholds_version=thresholds.version,
        thresholds_fingerprint=thresholds.fingerprint(),
        question_dag=dag,
        gate_transcript=transcript,
        retry_count=retry_count,
        decision=decision,
        attempts=list(attempts or []),
        checkpoint=checkpoint,
        image_path=gen.image_path,
        created_at=now.isoformat().replace("+00:00", "Z"),
        prompt=synth.prompt,
        negative_prompt=synth.negative_prompt,
    )
