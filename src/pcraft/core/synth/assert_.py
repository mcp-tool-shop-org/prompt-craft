"""Pre-generation Assert: every required atom must be covered BEFORE any GPU spend.

Catching an uncovered atom here (cheap) beats a failed generation + gate reject (expensive). On
failure the orchestrator backtracks and re-synthesizes with the missing-atom list injected
(DSPy Assertions). This is also the entry to ANDON: an asset whose required atoms aren't even
described can never reach generation, let alone bind."""

from __future__ import annotations

from ...errors import PromptCraftError
from ..contract.schema import ResolvedContract


def assert_coverage(resolved: ResolvedContract, atom_coverage: dict[str, str]) -> None:
    """Raise SYNTH_COVERAGE_MISSING listing any required atom with no non-empty coverage phrase."""
    missing = [a.id for a in resolved.required_atoms() if not atom_coverage.get(a.id, "").strip()]
    if missing:
        raise PromptCraftError(
            "SYNTH_COVERAGE_MISSING",
            f"{len(missing)} required atom(s) have no coverage phrase: {missing}",
            hint="Re-synthesize with these atom ids injected; do not generate until every "
            "required atom is covered.",
        )

    # Coverage may only reference real atoms (a typo'd atom_id is a synthesizer defect).
    known = {a.id for a in resolved.must_have}
    unknown = [aid for aid in atom_coverage if aid not in known]
    if unknown:
        raise PromptCraftError(
            "SYNTH_COVERAGE_UNKNOWN_ATOM",
            f"coverage references atom ids not in the contract: {unknown}",
        )
