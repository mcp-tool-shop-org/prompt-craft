"""Contrastive human checkpoint — UNCERTAINTY_GATED_HUMANS.

The gate already refuses a silent pass on UNCERTAIN. This is the artifact a
human reads: what you probably thought, what the gate chose, per flagged atom.
Without it the standard is a zone, not a checkpoint.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..contract.compile_questions import Polarity, QuestionDAG
from .harness import AtomVerdict, GateTranscript
from .thresholds import ThresholdTable, Zone


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


def _margin(verdict: AtomVerdict, thresholds: ThresholdTable | None) -> str:
    """``0.79`` alone, or ``0.79; vqa passes at 0.80, fails at 0.40`` (F-b1b29cef).

    The operator standing at this checkpoint is being asked to accept or repair, and the MARGIN
    is the input to that decision. MEASURED: skin scripted to 0.79 and to 0.41 -- one hundredth
    from PASS and one hundredth from FAIL under vqa 0.80/0.40 -- produced sentences that differed
    only in the number, so learning whether an UNCERTAIN was nearly a bind or nearly a failure
    meant opening sprite.calibration.json.

    ``thresholds`` is optional so a caller without a table renders exactly what it rendered
    before; ``band_key`` is empty whenever nothing scored, and an atom with no score has no
    margin to state.
    """
    score_txt = _score_text(verdict.score)
    if thresholds is None or not verdict.band_key or verdict.score is None:
        return score_txt
    band = thresholds.band_for(verdict.band_key)
    if verdict.polarity is Polarity.affirm:
        return f"{score_txt}; {verdict.band_key} passes at {band.high:.2f}, fails at {band.low:.2f}"
    return f"{score_txt}; {verdict.band_key} fails at {band.high:.2f}, passes at {band.low:.2f}"


def _line(
    verdict: AtomVerdict, dag: QuestionDAG | None, thresholds: ThresholdTable | None = None
) -> ContrastiveLine:
    question = dag.by_id(verdict.atom_id) if dag is not None else None
    claim = question.text if question is not None else verdict.atom_id
    score_txt = _margin(verdict, thresholds)
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


def _census_line(transcript: GateTranscript) -> ContrastiveLine | None:
    """The non-Zone cause, in the same contrastive voice (F-2c7b997a).

    ``build_checkpoint`` derived its entire content from Zone facts -- the header pair branches on
    ``transcript.overall`` and every line comes from ``failed_required()`` + ``uncertain_required()``
    -- and never read ``tier_census``, which is on the transcript it is handed. So for any
    escalation whose cause is not a Zone, this artifact was structurally incapable of naming the
    cause. That matters more than it sounds: the text becomes ``OrchestrationResult.reason`` and
    the CLI prints it verbatim, so the operator's only human-facing artifact said nothing while
    ``error_from_transcript`` beside it named the census, the required tiers and the executed ones.
    """
    census = transcript.tier_census
    if census.m == 0 or census.n >= census.m:
        return None
    return ContrastiveLine(
        atom_id="tier_census",
        zone=transcript.overall.value,
        claim=f"required tiers {census.required}, executed {census.executed}",
        thought="you probably thought the gate ran every instrument it needed",
        chose=f"I only executed {census.n} of {census.m} required tiers",
    )


def build_checkpoint(
    transcript: GateTranscript,
    dag: QuestionDAG | None = None,
    thresholds: ThresholdTable | None = None,
) -> ContrastiveCheckpoint:
    flagged = [*transcript.failed_required(), *transcript.uncertain_required()]
    lines = [_line(v, dag, thresholds) for v in flagged]
    census_line = _census_line(transcript)
    if census_line is not None:
        lines.append(census_line)
    no_required = transcript.declares_no_required_atom()
    if no_required:
        # Reachable, and it produced a statement that was false rather than merely uninformative:
        # MEASURED through sample.run_mock_loop with every severity set to optional, all ten atoms
        # scored and all ten passed, and the escalation reason read "You probably thought a missing
        # score was nothing to look at." on a run where nothing was missing. The roll-up is still
        # UNAVAILABLE and nothing still binds; only the account of WHY changes.
        lines.append(
            ContrastiveLine(
                atom_id="contract",
                zone=transcript.overall.value,
                claim=f"contract {transcript.contract_id}",
                thought="you probably thought a scored, all-passing run was a bind",
                chose="I escalated because this contract declares no required atom, so there was "
                "nothing the gate was allowed to block on",
            )
        )
        thought = "You probably thought every atom passing was enough."
        chose = "I escalated: nothing in this contract is required, so nothing was decided."
    elif transcript.overall is Zone.UNCERTAIN:
        thought = "You probably thought a near-miss was a pass."
        chose = "I chose the human band, not a bind."
    elif transcript.overall is Zone.FAIL:
        thought = "You probably thought finishing the loop meant the picture passed."
        chose = "I escalated on a required failure."
    elif transcript.overall is Zone.UNAVAILABLE:
        thought = "You probably thought a missing score was nothing to look at."
        chose = "I treated could-not-run as escalation, not a pass."
    elif census_line is not None:
        thought = "You probably thought a PASS meant the whole gate ran."
        chose = "I escalated on the tier census, which is independent of the zone."
    else:
        thought = "You probably thought nothing needed a human."
        chose = f"I escalated ({transcript.overall.value})."
    # The header pair is ONE line -- the summary -- and each flagged atom is its own indented
    # line below it. Keeping the pair joined by a space is what makes the two kinds of content
    # visibly different kinds; joining all of it identically was half of the defect below.
    parts = [f"{thought} {chose}"]
    # CORRECTED IN PLACE (F-a6acaab1). This separator was a literal U+2014 EM DASH. `text` is
    # not decoration: it becomes OrchestrationResult.reason and the CLI prints it verbatim, so
    # on a cp437 console -- classic cmd.exe -- an escalation died with an unhandled
    # UnicodeEncodeError inside click after writing the first banner line. That lands in
    # bind/demo's `except Exception` backstop, so the run reported error[RUNTIME_UNEXPECTED] at
    # exit 2 (whose own hint says "this code is the backstop, not a diagnosis") instead of the
    # escalation's 3 or 4 -- and the operator never saw the contrastive checkpoint at all. The
    # UNCERTAINTY_GATED_HUMANS artifact was exactly what the crash destroyed. ASCII, because it
    # is the only codepage-independent guarantee and this is advice, not typography.
    #
    # CORRECTED IN PLACE (F-a6078c7f). These parts were flattened with ``" ".join`` and shipped
    # as ONE unbroken line inside a parenthesis: ``text`` becomes OrchestrationResult.reason,
    # which cli._print_result prints as ``decision: ESCALATED  ({reason})``. MEASURED through
    # sample.run_mock_loop with the six required atoms at 0.05 and rendered through the real
    # cli._print_result: 974 characters, ZERO newlines, closing its parenthesis 974 characters
    # later -- while the formatted transcript printed twenty lines below it was fully structured.
    # The human decision point was the one artifact that was not, and STANDARDS #5 calls the
    # checkpoint the artifact, not the string. build_checkpoint already had the content as
    # STRUCTURE (one ContrastiveLine per flagged atom) and threw it away at the last step.
    #
    # Two smaller defects in the same expression went with it: the per-line template appended a
    # '.' to a claim that is already a question ("worn over the torso?." six times in that run),
    # and the header pair and the per-atom lines were joined identically, so nothing
    # distinguished the summary from the detail.
    #
    # F-a6acaab1's cp437 guarantee is untouched: a newline and "  - " are ASCII, which is the
    # only codepage-independent guarantee there is.
    parts.extend(
        f"  - {line.atom_id} {line.zone} {_score_text(line.score)}: "
        f"{line.thought}; {line.chose} -- {line.claim}"
        for line in lines
    )
    return ContrastiveCheckpoint(thought=thought, chose=chose, lines=lines, text="\n".join(parts))
