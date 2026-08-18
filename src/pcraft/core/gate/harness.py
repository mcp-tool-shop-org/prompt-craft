"""The gate harness: run a tiered set of Verifiers over the question DAG, dependency-ordered.

Routing is cheapest-decides-first: ``siglip2``/``palette`` atoms hit the Tier-0 screen; ``vqa`` atoms
hit Tier-1 (VQAScore); a Tier-1 UNCERTAIN/FAIL escalates to Tier-2 (DSG) for per-atom localization.
Evaluation is parent-first: a non-passing parent forces its children to N/A (a NO parent forces NO on
descendants). A required atom that cannot be confirmed (SKIPPED / NA / UNCERTAIN) never rolls up to a
silent PASS — it routes the whole asset to the UNCERTAIN (human) band."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

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


class TierCensus(BaseModel):
    """N of M required tiers actually executed. Independent of the verdict.

    M is the set of tiers the contract's required / must_not atoms map to.
    N is how many of those produced at least one score. A PASS with 1/2
    is a pass whose Tier-0 never ran — the watchdog, not a second verdict.
    """

    model_config = ConfigDict(extra="forbid")
    required: list[int] = Field(default_factory=list)
    executed: list[int] = Field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.executed)

    @property
    def m(self) -> int:
        return len(self.required)


class GateTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: str
    overall: Zone
    verdicts: list[AtomVerdict]
    tier_census: TierCensus = Field(default_factory=TierCensus)

    def failed_required(self) -> list[AtomVerdict]:
        return [v for v in self.verdicts if v.zone is Zone.FAIL and _counts(v)]

    def uncertain_required(self) -> list[AtomVerdict]:
        return [v for v in self.verdicts if v.zone in (Zone.UNCERTAIN, Zone.SKIPPED, Zone.NA) and _counts(v)]

    def scored_required(self) -> list[AtomVerdict]:
        """Required / must_not atoms that produced a numeric score."""
        return [v for v in self.verdicts if _counts(v) and v.score is not None]

    def could_not_run(self) -> bool:
        """No required atom produced a score. Distinct from UNCERTAIN-after-a-score."""
        return not self.scored_required()


def _counts(v: AtomVerdict) -> bool:
    """A verdict counts toward the overall roll-up if it is required.

    ⚑ CORRECTED IN PLACE. This read ``v.severity is Severity.required or v.polarity is
    Polarity.negate``. That ``or`` was not belt-and-braces — it OVERRODE severity, so a negation
    counted as blocking whatever its severity said. Harmless while ``MustNot`` had no severity
    field and every negation was required by construction; the moment a negation can be
    ``optional`` the same ``or`` makes that setting cosmetic — the atom reads optional in the
    contract and still blocks a bind.

    A negation blocks when its severity says so, exactly like an affirmation.
    """
    return v.severity is Severity.required


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
    return GateTranscript(
        contract_id=dag.contract_id,
        overall=_rollup(ordered),
        verdicts=ordered,
        tier_census=_tier_census(dag, ordered),
    )


def _skipped(q, reason: str) -> AtomVerdict:
    return AtomVerdict(
        atom_id=q.atom_id, polarity=q.polarity, severity=q.severity, score=None,
        zone=Zone.SKIPPED, tier_used=None, verifier_id=None, reason=reason,
    )


def _required_tiers(dag: QuestionDAG) -> list[int]:
    """Tiers the contract's REQUIRED atoms depend on — the denominator of the census.

    ⚑ CORRECTED IN PLACE, same defect as ``_counts``: the ``or q.polarity is Polarity.negate``
    counted a negation's tier as required regardless of severity. A contract whose only Tier-1
    user was an optional negation would then report that tier as required-but-not-executed and
    look like a dead verifier, when nothing blocking ever needed it.
    """
    tiers: set[int] = set()
    for q in dag.questions:
        if q.severity is Severity.required:
            tiers.add(_TIER_FOR_CHECK[q.check_type])
    return sorted(tiers)


def _tier_census(dag: QuestionDAG, verdicts: list[AtomVerdict]) -> TierCensus:
    required = _required_tiers(dag)
    executed = sorted({
        v.tier_used for v in verdicts
        if v.score is not None and v.tier_used is not None and v.tier_used in required
    })
    return TierCensus(required=required, executed=executed)


def _rollup(verdicts: list[AtomVerdict]) -> Zone:
    """The gate's own abstention, not a max over tier confidences.

    A mid-band score is UNCERTAIN (the atom was checked). A missing score is
    not UNCERTAIN — if nothing scored, the roll-up is UNAVAILABLE. Mixing
    those two into one Zone was the same merge the exit contract had to split.
    """
    relevant = [v for v in verdicts if _counts(v)]
    scored = [v for v in relevant if v.score is not None]
    if any(v.zone is Zone.FAIL for v in scored):
        return Zone.FAIL
    if not scored:
        return Zone.UNAVAILABLE
    if any(v.zone is Zone.UNCERTAIN for v in scored):
        return Zone.UNCERTAIN
    if any(v.zone in (Zone.SKIPPED, Zone.NA) for v in relevant):
        return Zone.UNCERTAIN
    return Zone.PASS
