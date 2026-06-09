"""The gate harness: run a tiered set of Verifiers over the question DAG, dependency-ordered.

Routing is cheapest-decides-first: ``siglip2``/``palette`` atoms hit the Tier-0 screen; ``vqa`` atoms
hit Tier-1 (VQAScore); a Tier-1 UNCERTAIN/FAIL escalates to Tier-2 (DSG) for per-atom localization.
Evaluation is parent-first: a non-passing parent forces its children to N/A (a NO parent forces NO on
descendants). A required atom that cannot be confirmed (SKIPPED / NA / UNCERTAIN) never rolls up to a
silent PASS — it routes the whole asset to the UNCERTAIN (human) band."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..contract.compile_questions import CheckType, Polarity, QuestionDAG, Severity
from .thresholds import ThresholdTable, Zone
from .verifier_iface import Verifier

# which gate tier owns each check_type
_TIER_FOR_CHECK = {CheckType.siglip2: 0, CheckType.palette: 0, CheckType.vqa: 1}


class AtomVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str
    polarity: Polarity
    severity: Severity
    score: float | None
    zone: Zone
    tier_used: int | None
    verifier_id: str | None
    reason: str


class GateTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: str
    overall: Zone
    verdicts: list[AtomVerdict]

    def failed_required(self) -> list[AtomVerdict]:
        return [v for v in self.verdicts if v.zone is Zone.FAIL and _counts(v)]

    def uncertain_required(self) -> list[AtomVerdict]:
        return [v for v in self.verdicts if v.zone in (Zone.UNCERTAIN, Zone.SKIPPED, Zone.NA) and _counts(v)]


def _counts(v: AtomVerdict) -> bool:
    """A verdict counts toward the overall roll-up if it is required or a must_not probe."""
    return v.severity is Severity.required or v.polarity is Polarity.negate


def _pick(check_type: CheckType, verifiers: dict[int, Verifier]) -> tuple[Verifier | None, int | None]:
    """Pick the verifier for a check_type, falling forward to the next available tier."""
    want = _TIER_FOR_CHECK[check_type]
    for tier in (want, 1, 2, 0):
        if tier in verifiers:
            return verifiers[tier], tier
    return None, None


def evaluate(
    dag: QuestionDAG,
    image_path: str,
    verifiers: dict[int, Verifier],
    thresholds: ThresholdTable,
) -> GateTranscript:
    verdicts: dict[str, AtomVerdict] = {}

    for q in dag.topological():
        # Parent gating: a non-passing parent forces this atom to N/A.
        if q.depends_on and q.depends_on in verdicts:
            parent_zone = verdicts[q.depends_on].zone
            if parent_zone in (Zone.FAIL, Zone.NA, Zone.SKIPPED):
                verdicts[q.atom_id] = AtomVerdict(
                    atom_id=q.atom_id, polarity=q.polarity, severity=q.severity,
                    score=None, zone=Zone.NA, tier_used=None, verifier_id=None,
                    reason=f"parent {q.depends_on!r} did not pass ({parent_zone.value})",
                )
                continue

        verifier, tier = _pick(q.check_type, verifiers)
        if verifier is None:
            verdicts[q.atom_id] = _skipped(q, "no verifier available for tier")
            continue

        score = verifier.score(image_path, q)
        if score is None:
            verdicts[q.atom_id] = _skipped(q, f"{verifier.verifier_id} unavailable")
            continue

        zone = thresholds.zone(q.check_type.value, score, q.polarity)
        used_id, used_tier = verifier.verifier_id, tier

        # Escalate a borderline/failed Tier-1 result to Tier-2 (DSG) for localization.
        if tier == 1 and zone in (Zone.UNCERTAIN, Zone.FAIL) and 2 in verifiers:
            score2 = verifiers[2].score(image_path, q)
            if score2 is not None:
                score, zone = score2, thresholds.zone(q.check_type.value, score2, q.polarity)
                used_id, used_tier = verifiers[2].verifier_id, 2

        verdicts[q.atom_id] = AtomVerdict(
            atom_id=q.atom_id, polarity=q.polarity, severity=q.severity,
            score=round(score, 4), zone=zone, tier_used=used_tier, verifier_id=used_id,
            reason=f"score {score:.4f} -> {zone.value}",
        )

    ordered = [verdicts[q.atom_id] for q in dag.questions]
    return GateTranscript(contract_id=dag.contract_id, overall=_rollup(ordered), verdicts=ordered)


def _skipped(q, reason: str) -> AtomVerdict:
    return AtomVerdict(
        atom_id=q.atom_id, polarity=q.polarity, severity=q.severity, score=None,
        zone=Zone.SKIPPED, tier_used=None, verifier_id=None, reason=reason,
    )


def _rollup(verdicts: list[AtomVerdict]) -> Zone:
    relevant = [v for v in verdicts if _counts(v)]
    zones = {v.zone for v in relevant}
    if Zone.FAIL in zones:
        return Zone.FAIL
    if zones & {Zone.UNCERTAIN, Zone.SKIPPED, Zone.NA}:
        return Zone.UNCERTAIN  # a required atom we could not confirm — never a silent pass
    return Zone.PASS
