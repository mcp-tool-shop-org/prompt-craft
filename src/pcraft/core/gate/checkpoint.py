"""Contrastive human checkpoint — UNCERTAINTY_GATED_HUMANS.

The gate already refuses a silent pass on UNCERTAIN. This is the artifact a
human reads: what you probably thought, what the gate chose, per flagged atom.
Without it the standard is a zone, not a checkpoint.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..contract.compile_questions import QuestionDAG
from .harness import AtomVerdict, GateTranscript
from .thresholds import Zone


class ContrastiveLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str
    zone: str
    score: float | None = None
    claim: str = ""
    thought: str
    chose: str


class ContrastiveCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thought: str
    chose: str
    lines: list[ContrastiveLine]
    text: str


def _score_text(score: float | None) -> str:
    return "no score" if score is None else f"{score:.2f}"


def _line(verdict: AtomVerdict, dag: QuestionDAG | None) -> ContrastiveLine:
    question = dag.by_id(verdict.atom_id) if dag is not None else None
    claim = question.text if question is not None else verdict.atom_id
    score_txt = _score_text(verdict.score)
    if verdict.zone is Zone.UNCERTAIN:
        thought = f"you probably thought {verdict.atom_id} was close enough"
        chose = f"I left {verdict.atom_id} in the human band ({score_txt})"
    elif verdict.zone is Zone.FAIL:
        thought = f"you probably thought {verdict.atom_id} passed because the loop finished"
        chose = f"I failed {verdict.atom_id} ({score_txt})"
    else:
        thought = f"you probably thought {verdict.atom_id} was checked"
        chose = f"I could not confirm {verdict.atom_id} ({verdict.zone.value})"
    return ContrastiveLine(
        atom_id=verdict.atom_id,
        zone=verdict.zone.value,
        score=verdict.score,
        claim=claim,
        thought=thought,
        chose=chose,
    )


def build_checkpoint(transcript: GateTranscript, dag: QuestionDAG | None = None) -> ContrastiveCheckpoint:
    flagged = [*transcript.failed_required(), *transcript.uncertain_required()]
    lines = [_line(v, dag) for v in flagged]
    if transcript.overall is Zone.UNCERTAIN:
        thought = "You probably thought a near-miss was a pass."
        chose = "I chose the human band, not a bind."
    elif transcript.overall is Zone.FAIL:
        thought = "You probably thought finishing the loop meant the picture passed."
        chose = "I escalated on a required failure."
    elif transcript.overall is Zone.UNAVAILABLE:
        thought = "You probably thought a missing score was nothing to look at."
        chose = "I treated could-not-run as escalation, not a pass."
    else:
        thought = "You probably thought nothing needed a human."
        chose = f"I escalated ({transcript.overall.value})."
    parts = [thought, chose]
    # CORRECTED IN PLACE (F-a6acaab1). This separator was a literal U+2014 EM DASH. `text` is
    # not decoration: it becomes OrchestrationResult.reason and the CLI prints it verbatim, so
    # on a cp437 console -- classic cmd.exe -- an escalation died with an unhandled
    # UnicodeEncodeError inside click after writing the first banner line. That lands in
    # bind/demo's `except Exception` backstop, so the run reported error[RUNTIME_UNEXPECTED] at
    # exit 2 (whose own hint says "this code is the backstop, not a diagnosis") instead of the
    # escalation's 3 or 4 -- and the operator never saw the contrastive checkpoint at all. The
    # UNCERTAINTY_GATED_HUMANS artifact was exactly what the crash destroyed. ASCII, because it
    # is the only codepage-independent guarantee and this is advice, not typography.
    parts.extend(f"{line.thought}; {line.chose} -- {line.claim}." for line in lines)
    return ContrastiveCheckpoint(thought=thought, chose=chose, lines=lines, text=" ".join(parts))
