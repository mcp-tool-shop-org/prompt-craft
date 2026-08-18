"""Map a gate transcript to a structured error, or None if the run is a PASS.

The verdict on the transcript stays honest (UNCERTAIN is UNCERTAIN). The
process exit is a different object: exit 0 means the gate ran and every
required atom passed. A check that cannot see its input, or that produced
no score, must not look like success to a caller reading the exit code.

  IO_GATE_INPUT      path unreadable — raised by preflight, not here
  GATE_UNAVAILABLE   no required atom produced a score (extras missing)
  GATE_FAIL          a required atom scored FAIL — may block
  PARTIAL_UNCONFIRMED required atom unconfirmed after at least one real score
  PARTIAL_TIER_CENSUS a required tier never executed, though every scored atom passed

tier_census and the Zone roll-up are deliberately two SEPARATE facts (see TierCensus's
docstring in harness.py) — a PASS is not allowed to hide a gate that quietly under-ran its own
instruments, so this function checks the census on its own rather than trusting that a short
census will always also surface as a non-PASS Zone.
"""

from __future__ import annotations

from ...errors import PromptCraftError
from .harness import GateTranscript
from .thresholds import Zone


def error_from_transcript(transcript: GateTranscript) -> PromptCraftError | None:
    """None means PASS (exit 0). Anything else is a refuse."""
    if transcript.could_not_run():
        skipped = [v.atom_id for v in transcript.verdicts if v.zone is Zone.SKIPPED]
        return PromptCraftError(
            "GATE_UNAVAILABLE",
            "the gate produced no score on any required atom"
            + (f" (skipped: {skipped})" if skipped else ""),
            hint="Install the [image] extra, or this run could not execute. "
            "It is not a pass.",
        )
    failed = transcript.failed_required()
    if failed:
        return PromptCraftError(
            "GATE_FAIL",
            "required atom(s) failed: " + ", ".join(v.atom_id for v in failed),
            hint="A failed required atom blocks. Identity still gates nothing.",
        )
    if transcript.overall is Zone.UNCERTAIN:
        unconfirmed = [v.atom_id for v in transcript.uncertain_required()]
        return PromptCraftError(
            "PARTIAL_UNCONFIRMED",
            "required atom(s) unconfirmed after a real score: " + ", ".join(unconfirmed),
            hint="This is the human band, not a pass. Exit 3 (PARTIAL_), not 0, not 4.",
        )
    census = transcript.tier_census
    if census.n < census.m:
        # Independent watchdog check (kept separate from the Zone branches above on purpose —
        # see the module docstring). Not reachable via harness.evaluate() today: a required
        # atom that skips a tier now forces Zone.UNCERTAIN on its own (F-175c3b3e), and an
        # escalated atom now credits every tier it consulted (F-d9b28ca6). This is the net
        # underneath those two facts, not a rename of either.
        return PromptCraftError(
            "PARTIAL_TIER_CENSUS",
            f"only {census.n} of {census.m} required tiers executed "
            f"(required={census.required}, executed={census.executed}), "
            "though every scored atom passed",
            hint="A PASS whose gate under-ran its own instruments is not a pass. "
            "Exit 3 (PARTIAL_), not 0 — the tier census is independent of the zone.",
        )
    return None
