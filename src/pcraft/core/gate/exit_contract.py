"""Map a gate transcript to a structured error, or None if the run is a PASS.

The verdict on the transcript stays honest (UNCERTAIN is UNCERTAIN). The
process exit is a different object: exit 0 means the gate ran and every
required atom passed. A check that cannot see its input, or that produced
no score, must not look like success to a caller reading the exit code.

  IO_GATE_INPUT      path unreadable — raised by preflight, not here
  CONTRACT_NO_REQUIRED_ATOM  the contract declares nothing the gate may block on
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
    if transcript.declares_no_required_atom():
        # F-2c7b997a. This branch used to be inside could_not_run(), so a run in which every
        # verifier scored and every atom passed was answered GATE_UNAVAILABLE at exit 4, and that
        # code's hint says "Install the [image] extra ... so a verifier can score". The refusal
        # itself is right -- a gate with nothing it may block on has decided nothing, and nothing
        # binds -- but the defect is in the CONTRACT, not in the environment, so it takes a
        # CONTRACT_ code at exit 1 like every other contract-authoring refusal.
        return PromptCraftError(
            "CONTRACT_NO_REQUIRED_ATOM",
            f"contract {transcript.contract_id!r} declares no required atom, so the gate has "
            f"nothing it may block on ({len(transcript.verdicts)} atom(s) evaluated, all optional)",
        )
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
        # CORRECTED IN PLACE (F-56203d3d). This branch is the gate's entire purpose and the code
        # every content failure lands on, and its message carried only the failed atom ids.
        # MEASURED, real ``pcraft gate`` on a stub PNG with no [image] extra:
        # ``error[GATE_FAIL]: required atom(s) failed: palette`` at exit 2, on a transcript where
        # four required atoms were SKIPPED ('vqascore.clip-flant5.v1 unavailable'), a fifth was NA
        # behind a skipped parent, only ONE of six required atoms produced a score at all, and the
        # census line printed above read 'tiers executed: 1 of 2'. The exit code is defensible --
        # a real FAIL is a real FAIL -- but the STRUCTURED error is the only thing a CI job, an
        # MCP client or an LLM consumer sees, and it said a content atom failed while saying
        # nothing about the half-installed gate that skipped the other five. That is the plain
        # ``pip install prompt-craft`` experience, not an exotic path.
        #
        # Every fact below is already on the transcript; none of it is recomputed here.
        parts = ["required atom(s) failed: " + ", ".join(v.atom_id for v in failed)]
        required = transcript.required_atoms()
        unscored = [v for v in required if v.score is None]
        if unscored:
            by_zone: dict[str, list[str]] = {}
            for v in unscored:
                by_zone.setdefault(v.zone.value, []).append(v.atom_id)
            detail = "; ".join(f"{zone}: {', '.join(ids)}" for zone, ids in sorted(by_zone.items()))
            parts.append(
                f"{len(unscored)} of {len(required)} required atoms produced no score ({detail})"
            )
        census = transcript.tier_census
        if census.m:
            parts.append(f"{census.n} of {census.m} required tiers executed")
        return PromptCraftError("GATE_FAIL", "; ".join(parts))
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
            # F-a6acaab1: this inline hint carried a U+2014 EM DASH and was missed by the
            # wave-2 sweep because it is not a DEFAULT_HINTS entry. Same class as the
            # checkpoint crash, not yet on a reachable path -- to_safe_text() raises on
            # .encode('cp437') either way.
            hint="A PASS whose gate under-ran its own instruments is not a pass. "
            "Exit 3 (PARTIAL_), not 0 -- the tier census is independent of the zone.",
        )
    return None
