"""Human-readable rendering of a gate transcript (for the CLI and demo output).

PARTIAL / FAIL / UNAVAILABLE must not read as a wall of green PASSes with
one asterisk (To Trust or to Think, arXiv:2102.09692). Unconfirmed and
failed atoms print first. The tier census is its own line, not a log.
"""

from __future__ import annotations

from .core.contract.compile_questions import QuestionDAG
from .core.gate.harness import AtomVerdict, GateTranscript
from .core.gate.thresholds import Zone


def format_transcript(t: GateTranscript, *, dag: QuestionDAG | None = None) -> str:
    """Render a transcript for a human.

    ``dag`` is optional and additive (F-56203d3d). Without it this prints atom IDS only, so
    ``palette`` and ``no_rival_colours`` appear without the claims they are asserting -- while
    ``build_checkpoint`` one file over does print them, and ``pcraft gate`` compiles the DAG
    before calling this and then drops it. With it, each PROBLEM atom carries the question that
    was actually asked; passing rows do not, because a wall of claims under every green row is
    the "wall of green PASSes with one asterisk" this module's own docstring refuses.

    Keyword-only on purpose: the two shipped call sites pass one positional argument, and a
    keyword makes it impossible for a later caller to bind the wrong object into this slot.
    """
    census = t.tier_census
    lines = [
        f"gate overall: {t.overall.value}  (contract {t.contract_id})",
        f"thresholds: {t.thresholds_version or 'unversioned'}",
        f"tiers executed: {census.n} of {census.m}  "
        f"(executed {census.executed}; required {census.required})",
    ]
    problem = [
        v for v in t.verdicts
        if v.zone in (Zone.FAIL, Zone.UNCERTAIN, Zone.SKIPPED, Zone.NA, Zone.UNAVAILABLE)
    ]
    rest = [v for v in t.verdicts if v not in problem]
    if problem and t.overall is not Zone.PASS:
        lines.append("unconfirmed / failed:")
        for v in problem:
            lines.append(_fmt(v))
            lines.extend(_claim(v, dag))
        if rest:
            lines.append("other atoms:")
            lines.extend(_fmt(v) for v in rest)
    else:
        lines.extend(_fmt(v) for v in t.verdicts)
    return "\n".join(lines)


def _claim(v: AtomVerdict, dag: QuestionDAG | None) -> list[str]:
    """The question this atom actually asked, under the row that reports it failing."""
    if dag is None:
        return []
    question = dag.by_id(v.atom_id)
    if question is None or not question.text:
        return []
    return [f"{'':>24}claim: {question.text}"]


def _fmt(v: AtomVerdict) -> str:
    score = f"{v.score:.3f}" if v.score is not None else "  -  "
    tier = f"T{v.tier_used}" if v.tier_used is not None else "--"
    # ``detail`` is what the instrument SAW -- which colours of the palette it hit, where the
    # localizer looked -- and it is rendered on the verdict line for the same reason the band
    # numbers are (F-b1b29cef): the score says which side of the line, and nothing else on the
    # line says why. Absent for any verifier that does not publish one, which is the normal case,
    # and an absent detail renders exactly the string this function returned before it existed.
    detail = f"  [{v.detail}]" if v.detail else ""
    return (
        f"  [{v.zone.value:11}] {v.atom_id:18} {score} {tier}  "
        f"({v.polarity.value}/{v.severity.value})  {v.reason}{detail}"
    )
