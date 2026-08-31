"""Verdict machine + retry/repair policy, ported from the dogfood-labs swarm control plane.

The two-verdict enum (AMEND / ADVANCE) is the loop's control signal.

  AMEND   = fix-and-re-verify: regenerate/repair with the gate findings as input, then re-verify
  ADVANCE = every required atom passed AND the tier census confirms the gate actually ran on
            every required tier — proceed to bind

⚑ CORRECTED IN PLACE (F-a250372c): this enum previously also carried BLOCK and VERIFY, inherited
from the swarm-control-plane state machine this was ported from. Neither was ever constructed or
compared anywhere in this codebase (confirmed by grep across the whole repo, not just this
domain). VERIFY named a pre-gate state ("output produced but the gate hasn't run yet") that
verdict_from_transcript structurally never sees — it only ever runs on an already-built
GateTranscript, i.e. after the gate ran. BLOCK named a real gap (a structurally un-repairable
transcript, e.g. Zone.UNAVAILABLE, used to burn the whole repair budget identically to an ordinary
recoverable FAIL before escalating). The skip now lives in ``is_unrepairable`` — consulted by
``_repair_ladder`` — without adding a third Verdict member. Do not re-add BLOCK without a
construction site that is more than this skip.

Retry-eligibility splits by outcome class (state-machine.js): a TRANSIENT failure (generate error /
timeout) auto-retries; a SEMANTIC defect (schema-invalid synth output) is human-gated, never an
automatic re-roll. The VERIFIER — not the synthesizer — is the selector among candidates."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ..contract.compile_questions import QuestionDAG
from ..gate.harness import GateTranscript
from ..gate.thresholds import Zone


class Verdict(StrEnum):
    AMEND = "AMEND"
    ADVANCE = "ADVANCE"


class OutcomeClass(StrEnum):
    TRANSIENT = "transient"  # auto-retry: generate error / timeout
    SEMANTIC = "semantic"  # non-retryable: schema-invalid output, contract relaxation, missing dep


class RepairAction(StrEnum):
    INPAINT_REGION = "inpaint_region"  # leaf-attribute fail, object present -> regional inpaint, same seed
    RESYNTH_REWEIGHT = "resynth_reweight"  # composition / multiple fails -> re-synthesize, regenerate
    REROLL_NEW_SEED = "reroll_new_seed"  # presence / anatomy fail -> reject + reroll, new seed
    STRENGTHEN_IDENTITY = "strengthen_identity"  # identity/uniform atom failing -> raise IP-Adapter weight


class Attempt(BaseModel):
    """One generate+gate step. The receipt stores the list so a bind is not just a count."""

    model_config = ConfigDict(extra="forbid")
    attempt: int
    seed: int
    overall: Zone
    verdict: Verdict
    repair: RepairAction | None = None
    note: str = ""


class RetryBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inpaints: int = 1
    reprompts: int = 2
    rerolls: int = 4  # best-of-N default N=4
    best_of_n: int = 4

    def exhausted(self) -> bool:
        return self.inpaints <= 0 and self.reprompts <= 0 and self.rerolls <= 0


# STRENGTHEN_IDENTITY is a repair on the identity_ref plate, not a gate.
# A presence atom whose id happens to contain "face" or "palette" is not
# that plate. Substring match was the back door: it treated a garment /
# species claim as likeness. Only an atom that IS the plate may request
# the plate-weight bump. None of the scaffold atoms are that object.
_IDENTITY_REPAIR_IDS = frozenset({"identity", "identity_ref"})


def _is_identity_atom(atom_id: str) -> bool:
    return atom_id.lower() in _IDENTITY_REPAIR_IDS


def is_unrepairable(transcript: GateTranscript) -> bool:
    """True when another seed cannot change the outcome.

    The repair ladder re-generates pixels. It cannot install a missing verifier,
    invent a score where none existed, or execute a required tier that is not
    registered. UNAVAILABLE, a could-not-run census, and a short tier census are
    therefore skipped rather than burned.
    """
    if transcript.overall is Zone.UNAVAILABLE:
        return True
    if transcript.could_not_run():
        return True
    census = transcript.tier_census
    return census.m > 0 and census.n < census.m


def verdict_from_transcript(transcript: GateTranscript) -> Verdict:
    """Map a gate transcript to a loop verdict. PASS -> ADVANCE; any required FAIL -> AMEND
    (repair); UNCERTAIN-only -> AMEND too (route through the repair/human path, never silent pass).

    ADVANCE also requires the tier census to be complete: Zone and the census are two independent
    facts and neither is folded into the other (the roll-up to Zone.PASS is still computed purely
    from Zone; the census is consulted here as a second, separate gate on top of it).

    CORRECTED IN PLACE (F-c1832100). This paragraph used to justify the census with a "Reachable
    example": a required atom's home tier is unregistered, ``harness._pick`` falls forward to a
    different tier's verifier, and that score clears the band for the atom's nominal check_type,
    so Zone rolls up to PASS while the required tier never ran. That mechanism was REMOVED by
    F-175c3b3e -- ``_pick`` returns ``(None, None)`` for a missing tier and the atom is SKIPPED --
    and ``exit_contract.error_from_transcript`` says so directly on its own census branch ("Not
    reachable via harness.evaluate() today"). One docstring calling the scenario reachable while
    a sibling in the same domain calls it unreachable, both citing the same fix id, is the defect
    class this package exists to catch. The bare tracker id it cited alongside that example
    resolved nowhere in this repo except itself and the test that copied it, so it is dropped
    rather than redefined -- naming a dead identifier is what keeps it looking alive.

    What the census actually is: the independent net UNDERNEATH the Zone roll-up, not a path
    ``harness.evaluate`` can reach today. It is kept deliberately so a future routing change
    cannot make a short census invisible again -- defence in depth, stated as such.

    TierCensus.executed is filtered to tiers already in .required (harness._tier_census), so n can
    never exceed m -- a plain ``n < m`` check is equivalent to requiring ``n == m``."""
    census = transcript.tier_census
    if transcript.overall is Zone.PASS and census.n >= census.m:
        return Verdict.ADVANCE
    return Verdict.AMEND


def choose_repair(transcript: GateTranscript, budget: RetryBudget, dag: QuestionDAG) -> RepairAction:
    """Route the worst failed atom by its DAG level to a repair action (the repair ladder)."""
    failed = transcript.failed_required() or transcript.uncertain_required()

    # identity/uniform atom still failing -> STRENGTHEN identity_ref, not prompt edits
    if any(_is_identity_atom(v.atom_id) for v in failed):
        return RepairAction.STRENGTHEN_IDENTITY

    # a presence atom (one that other atoms depend_on) failing -> reject + reroll, new seed
    presence_ids = {q.depends_on for q in dag.questions if q.depends_on}
    if any(v.atom_id in presence_ids for v in failed):
        return RepairAction.REROLL_NEW_SEED

    # multiple distinct fails -> re-synthesize with the failed atoms re-weighted
    if len(failed) > 1 and budget.reprompts > 0:
        return RepairAction.RESYNTH_REWEIGHT

    # a single leaf-attribute fail with budget -> regional inpaint, same seed
    if budget.inpaints > 0:
        return RepairAction.INPAINT_REGION
    return RepairAction.REROLL_NEW_SEED


# CORRECTED IN PLACE (F-9ee95e14). ``DEP_`` and ``RUNTIME_GENERATOR_LOAD_FAILED`` used to fall
# through to TRANSIENT, so the loop re-rolled them for the whole best-of-N budget -- and for a real
# generator each retry re-attempts a model load. A second seed does not install torch and does not
# repair a checkpoint: these cannot succeed on a retry, so retrying them is pure waste that also
# destroys the one error whose hint was the actual answer. They are non-retryable by name, not by
# widening the RUNTIME_ prefix, because a plain RUNTIME_ timeout is exactly what best-of-N is for.
_SEMANTIC_PREFIXES = ("SYNTH_", "CONTRACT_", "GATE_", "INPUT_", "DEP_")
_SEMANTIC_CODES = frozenset({"RUNTIME_GENERATOR_LOAD_FAILED"})


def classify_failure(error_code: str) -> OutcomeClass:
    """Transient (auto-retry) vs semantic (non-retryable, human-gated). Mirrors state-machine.js
    BLOCKED vs REDISPATCHABLE: schema/contract defects and unsatisfiable preconditions are blocked;
    transient runtime errors redispatch."""
    if error_code in _SEMANTIC_CODES or any(error_code.startswith(p) for p in _SEMANTIC_PREFIXES):
        return OutcomeClass.SEMANTIC
    return OutcomeClass.TRANSIENT
