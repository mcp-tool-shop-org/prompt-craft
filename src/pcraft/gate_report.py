"""Human-readable rendering of a gate transcript (for the CLI and demo output).

PARTIAL / FAIL / UNAVAILABLE must not read as a wall of green PASSes with
one asterisk (To Trust or to Think, arXiv:2102.09692). Unconfirmed and
failed atoms print first. The tier census is its own line, not a log.
"""

from __future__ import annotations

from .core.gate.harness import AtomVerdict, GateTranscript
from .core.gate.thresholds import Zone


def format_transcript(t: GateTranscript) -> str:
    census = t.tier_census
    lines = [
        f"gate overall: {t.overall.value}  (contract {t.contract_id})",
        f"tiers executed: {census.n} of {census.m}  "
        f"(executed {census.executed}; required {census.required})",
    ]
    problem = [v for v in t.verdicts if v.zone in (Zone.FAIL, Zone.UNCERTAIN, Zone.SKIPPED, Zone.NA)]
    rest = [v for v in t.verdicts if v not in problem]
    if problem and t.overall is not Zone.PASS:
        lines.append("unconfirmed / failed:")
        lines.extend(_fmt(v) for v in problem)
        if rest:
            lines.append("other atoms:")
            lines.extend(_fmt(v) for v in rest)
    else:
        lines.extend(_fmt(v) for v in t.verdicts)
    return "\n".join(lines)


def _fmt(v: AtomVerdict) -> str:
    score = f"{v.score:.3f}" if v.score is not None else "  -  "
    tier = f"T{v.tier_used}" if v.tier_used is not None else "--"
    return (
        f"  [{v.zone.value:11}] {v.atom_id:18} {score} {tier}  "
        f"({v.polarity.value}/{v.severity.value})  {v.reason}"
    )
