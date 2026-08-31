"""Pre-generation Assert: every required atom must be covered BEFORE any GPU spend.

Catching an uncovered atom here (cheap) beats a failed generation + gate reject (expensive). On
failure the orchestrator backtracks and re-synthesizes with the missing-atom list injected
(DSPy Assertions). This is also the entry to ANDON: an asset whose required atoms aren't even
described can never reach generation, let alone bind."""

from __future__ import annotations

from ...errors import PromptCraftError
from ..contract.schema import ResolvedContract


def assert_coverage(resolved: ResolvedContract, atom_coverage: dict[str, str]) -> None:
    """Raise SYNTH_COVERAGE_MISSING listing any required atom with no non-empty coverage phrase.

    The message names each missing atom's CLAIM alongside its id (F-27344f8e). It used to name
    ids only -- "2 required atom(s) have no coverage phrase: ['tabard', 'sigil']" -- so the
    person this refusal is aimed at, someone actively tuning a template or a synthesizer, had to
    reopen the contract file to recall what 'tabard' actually claims before they could act on it.
    This function is already holding the resolved contract, so the claim text costs a lookup it
    was choosing not to do. The sibling guard in ``visual_inventory`` (assert_tokens_trace /
    SYNTH_PROSE_DUMP) already names the offending prompt segments rather than a count, and this
    is the same standard applied to the other half of the pre-generation gate.

    The atoms are carried through rather than re-resolved by id: ``missing`` is built FROM
    ``required_atoms()``, so every entry has its claim in hand and there is no
    ``atom_by_id`` return that a reader has to prove non-None.
    """
    missing = [a for a in resolved.required_atoms() if not atom_coverage.get(a.id, "").strip()]
    if missing:
        named = ", ".join(f"{a.id} ({a.claim!r})" for a in missing)
        raise PromptCraftError(
            "SYNTH_COVERAGE_MISSING",
            f"{len(missing)} required atom(s) have no coverage phrase: {named}",
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
