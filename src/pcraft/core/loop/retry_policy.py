"""Verdict machine + retry/repair policy, ported from the dogfood-labs swarm control plane.

The four-verdict enum (BLOCK / AMEND / VERIFY / ADVANCE) is the loop's control signal — its control
flow is reused as-is; only the gate *bodies* are swapped for prompt-craft's synth/generate/verify.

  BLOCK   = halt, the defect cannot propagate downstream (andon authority)
  AMEND   = fix-and-re-verify: regenerate/repair with the gate findings as input, then re-verify
  VERIFY  = output produced but the gate hasn't run yet — run it before any verdict
  ADVANCE = all gates green — proceed to bind

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
    BLOCK = "BLOCK"
    AMEND = "AMEND"
    VERIFY = "VERIFY"
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


# atom ids whose failure should escalate identity conditioning rather than prompt edits
def _is_identity_atom(atom_id: str) -> bool:
    return any(tok in atom_id.lower() for tok in ("face", "sigil", "identity", "insignia", "palette"))


def verdict_from_transcript(transcript: GateTranscript) -> Verdict:
    """Map a gate transcript to a loop verdict. PASS -> ADVANCE; any required FAIL -> AMEND
    (repair); UNCERTAIN-only -> AMEND too (route through the repair/human path, never silent pass)."""
    if transcript.overall is Zone.PASS:
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
