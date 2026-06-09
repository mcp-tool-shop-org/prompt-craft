"""Human-readable rendering of a gate transcript (for the CLI and demo output)."""

from __future__ import annotations

from .core.gate.harness import GateTranscript


def format_transcript(t: GateTranscript) -> str:
    lines = [f"gate overall: {t.overall.value}  (contract {t.contract_id})"]
    for v in t.verdicts:
        score = f"{v.score:.3f}" if v.score is not None else "  -  "
        tier = f"T{v.tier_used}" if v.tier_used is not None else "--"
        lines.append(
            f"  [{v.zone.value:9}] {v.atom_id:18} {score} {tier}  "
            f"({v.polarity.value}/{v.severity.value})  {v.reason}"
        )
    return "\n".join(lines)
