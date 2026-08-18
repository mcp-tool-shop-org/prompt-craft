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

from enum import Enum

from pydantic import BaseModel, ConfigDict

from ..contract.compile_questions import QuestionDAG
from ..gate.harness import GateTranscript
from ..gate.thresholds import Zone


class Verdict(str, Enum):
    AMEND = "AMEND"
    ADVANCE = "ADVANCE"


class OutcomeClass(str, Enum):
    TRANSIENT = "transient"  # auto-retry: generate error / timeout
    SEMANTIC = "semantic"  # human-gated: schema-invalid output, contract relaxation


class RepairAction(str, Enum):
    INPAINT_REGION = "inpaint_region"  # leaf-attribute fail, object present -> regional inpaint, same seed
    RESYNTH_REWEIGHT = "resynth_reweight"  # composition / multiple fails -> re-synthesize, regenerate
    REROLL_NEW_SEED = "reroll_new_seed"  # presence / anatomy fail -> reject + reroll, new seed
    STRENGTHEN_IDENTITY = "strengthen_identity"  # identity/uniform atom failing -> raise IP-Adapter weight


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
    from Zone; the census is consulted here as a second, separate gate on top of it). Reachable
    example: a required atom's home tier is unregistered, harness._pick falls forward to a
    different tier's verifier, and that verifier's score happens to clear the band for the atom's
    *nominal* check_type — Zone rolls up to PASS, but the atom's actually-required tier never ran
    (see GATE-002). TierCensus.executed is filtered to tiers already in .required
    (harness._tier_census), so n can never exceed m — a plain ``n < m`` check is equivalent to
    requiring ``n == m``."""
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


def classify_failure(error_code: str) -> OutcomeClass:
    """Transient (auto-retry) vs semantic (human-gated). Mirrors state-machine.js BLOCKED vs
    REDISPATCHABLE: schema/contract defects are blocked; transient runtime errors redispatch."""
    semantic_prefixes = ("SYNTH_", "CONTRACT_", "GATE_", "INPUT_")
    if any(error_code.startswith(p) for p in semantic_prefixes):
        return OutcomeClass.SEMANTIC
    return OutcomeClass.TRANSIENT
