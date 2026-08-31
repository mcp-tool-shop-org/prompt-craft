"""The gate harness: run a tiered set of Verifiers over the question DAG, dependency-ordered.

Routing is cheapest-decides-first: ``siglip2``/``palette`` atoms hit the Tier-0 screen; ``vqa`` atoms
hit Tier-1 (VQAScore); a Tier-1 UNCERTAIN/FAIL escalates to Tier-2 (DSG) for per-atom localization.
Evaluation is parent-first: a non-passing parent forces its children to N/A (a NO parent forces NO on
descendants), and a ``depends_on`` naming no atom in this contract is SKIPPED, not treated as an atom
with no parent. A required atom that cannot be confirmed (SKIPPED / NA / UNCERTAIN) never rolls up to
a silent PASS -- it routes the whole asset to the UNCERTAIN (human) band."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from ...errors import PromptCraftError
from ..contract.compile_questions import CheckType, Polarity, Question, QuestionDAG, Severity
from .family_guard import assert_distinct_families
from .thresholds import ThresholdTable, Zone
from .verifier_iface import Verifier, forbid_clipscore

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
    tiers_consulted: list[int] = Field(default_factory=list)
    verifier_id: str | None
    reason: str


class TierCensus(BaseModel):
    """N of M required tiers actually executed. Independent of the verdict.

    M is the set of tiers the contract's required / must_not atoms map to.
    N is how many of those produced at least one score. This is the watchdog, not a second
    verdict: a 1/2 census means Tier-0 never ran, full stop, regardless of what Zone the atoms
    that DID score rolled up to. Nothing here computes a Zone from n/m (see ``error_from_transcript``
    for the exit-code consequence) — a 1/2 census used to still coexist with an overall PASS,
    which is exactly the hole F-175c3b3e/F-d9b28ca6 closed (a required atom that never gets a
    real score is SKIPPED, and SKIPPED never rolls up to PASS).
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
    thresholds_version: str = ""

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
    """Pick the verifier for a check_type's OWN tier. No cross-tier fallback.

    ⚑ CORRECTED IN PLACE (F-175c3b3e). This used to fall forward to whichever tier WAS
    registered (``for tier in (want, 1, 2, 0)``) when the wanted tier was missing. The score
    that verifier returned was then graded via ``thresholds.zone(q.check_type.value, ...)`` --
    keyed purely by the atom's declared check_type, with no relationship to which verifier
    actually produced the number. Real shipped bands are almost an order of magnitude apart
    (siglip2 high=0.10 vs vqa high=0.80), so a substituted verifier's own confident answer could
    read as a confident answer on the WRONG scale: a false PASS or a false FAIL, not merely an
    unconfirmed one. A missing tier is now SKIPPED, exactly like a verifier that returned
    ``None`` -- never a guess scored on someone else's calibration.
    """
    want = _TIER_FOR_CHECK[check_type]
    return (verifiers[want], want) if want in verifiers else (None, None)


def evaluate(
    dag: QuestionDAG,
    image_path: str,
    verifiers: dict[int, Verifier],
    thresholds: ThresholdTable,
    *,
    generator_family: str,
) -> GateTranscript:
    """Run the gate. ``generator_family`` is required, not optional: EXTERNAL_VERIFIER is
    enforced HERE, at the protected operation, so every caller gets it -- not only the ones
    that remember to call ``forbid_clipscore``/``assert_distinct_families`` themselves first
    (F-461c4198: ``orchestrate.run()`` did; the standalone ``pcraft gate`` CLI command, which
    calls this function directly, did not)."""
    for v in verifiers.values():
        forbid_clipscore(v)
    assert_distinct_families(generator_family, [v.family for v in verifiers.values()])

    verdicts: dict[str, AtomVerdict] = {}

    for q in dag.topological():
        # Parent gating: a non-passing parent forces this atom to N/A.
        if q.depends_on:
            # CORRECTED IN PLACE (F-19f97de2). This branch read
            # ``if q.depends_on and q.depends_on in verdicts:``. The ``in verdicts`` clause was
            # not a guard, it was a silent DELETE: it turned "the declared parent could not be
            # resolved" into "this atom has no parent", and the atom was then scored on its own
            # -- no error, no SKIPPED, no reason string, nothing in the transcript recording that
            # the edge had been dropped. Nothing upstream catches it either: QuestionDAG
            # .topological() applies the identical ``depends_on in index`` guard, so a dangling
            # edge never even raises a KeyError here. Measured consequence: retyping one edge to
            # a one-character typo took a child from NA (its parent was judged absent) to a
            # confident PASS, and flipped the loop verdict from AMEND (escalate) to ADVANCE
            # (bind to canon), with a clean tier census in both runs -- so the ANDON watchdog
            # never saw it. An unresolvable parent is now an explicit outcome. SKIPPED already
            # never rolls up to PASS, so this closes the hole without inventing a new zone.
            parent = verdicts.get(q.depends_on)
            if parent is None:
                verdicts[q.atom_id] = _skipped(
                    q, f"parent {q.depends_on!r} is not an atom in this contract"
                )
                continue
            if parent.zone in (Zone.FAIL, Zone.NA, Zone.SKIPPED):
                verdicts[q.atom_id] = AtomVerdict(
                    atom_id=q.atom_id, polarity=q.polarity, severity=q.severity,
                    score=None, zone=Zone.NA, tier_used=None, verifier_id=None,
                    reason=f"parent {q.depends_on!r} did not pass ({parent.zone.value})",
                )
                continue

        verifier, tier = _pick(q.check_type, verifiers)
        if verifier is None or tier is None:
            # _pick returns both or neither; testing `tier` too is what makes that
            # invariant checkable rather than assumed (and keeps `tiers_consulted`
            # a list[int], not list[int | None]).
            verdicts[q.atom_id] = _skipped(q, "no verifier available for tier")
            continue

        score, skip_reason = _safe_score(verifier, image_path, q)
        if score is None:
            verdicts[q.atom_id] = _skipped(q, skip_reason or f"{verifier.verifier_id} unavailable")
            continue

        zone = thresholds.zone(q.check_type.value, score, q.polarity)
        used_id, used_tier = verifier.verifier_id, tier
        tiers_consulted = [tier]

        # Escalate a borderline/failed Tier-1 result to Tier-2 (DSG) for localization.
        if tier == 1 and zone in (Zone.UNCERTAIN, Zone.FAIL) and 2 in verifiers:
            score2, _skip2 = _safe_score(verifiers[2], image_path, q)
            if score2 is not None:
                score, zone = score2, thresholds.zone(q.check_type.value, score2, q.polarity)
                used_id, used_tier = verifiers[2].verifier_id, 2
                # ⚑ CORRECTED IN PLACE (F-d9b28ca6). used_tier used to be overwritten with no
                # record that Tier-1 ran first -- Tier-1's UNCERTAIN/FAIL score is what
                # triggered this escalation, so it necessarily ran. tier_used keeps meaning
                # "the tier whose score decided the verdict"; tiers_consulted is the separate,
                # additive fact the census actually needs: every tier that produced a real
                # score for this atom, escalated or not.
                tiers_consulted.append(2)

        verdicts[q.atom_id] = AtomVerdict(
            atom_id=q.atom_id, polarity=q.polarity, severity=q.severity,
            score=round(score, 4), zone=zone, tier_used=used_tier, tiers_consulted=tiers_consulted,
            verifier_id=used_id,
            reason=f"score {score:.4f} -> {zone.value}",
        )

    ordered = [verdicts[q.atom_id] for q in dag.questions]
    return GateTranscript(
        contract_id=dag.contract_id,
        overall=_rollup(ordered),
        verdicts=ordered,
        tier_census=_tier_census(dag, ordered),
        thresholds_version=thresholds.version,
    )


def _safe_score(verifier: Verifier, image_path: str, question: Question) -> tuple[float | None, str | None]:
    """Call ``verifier.score`` and reject anything that is not a finite value in [0, 1].

    ``None`` (or a rejected value) is SKIPPED, never a silent PASS/FAIL/UNCERTAIN.
    A coded ``PromptCraftError`` from the verifier is a defect, not a missing score,
    and is left to propagate. Any other exception is treated as unavailable.
    """
    try:
        raw = verifier.score(image_path, question)
    except PromptCraftError:
        raise
    except Exception as err:  # noqa: BLE001 - instrument crash is "could not score", not a zone
        return None, f"{verifier.verifier_id} raised {type(err).__name__}: {err}"
    if raw is None:
        return None, f"{verifier.verifier_id} unavailable"
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None, f"{verifier.verifier_id} rejected score {raw!r} (not numeric)"
    if math.isnan(score) or math.isinf(score) or score < 0.0 or score > 1.0:
        return None, f"{verifier.verifier_id} rejected score {raw!r} (need finite [0, 1])"
    return score, None


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
    """⚑ CORRECTED IN PLACE (F-d9b28ca6). This read ``v.tier_used`` -- the tier that decided the
    FINAL verdict -- so an atom that escalated Tier-1 -> Tier-2 only ever credited Tier-2 (never
    in ``required``; escalation is not a required tier), erasing the fact that Tier-1 ran too.
    Union across ``tiers_consulted`` instead: every tier that produced a real score for the atom,
    not just the one that decided it."""
    required = _required_tiers(dag)
    executed = sorted({tier for v in verdicts for tier in v.tiers_consulted if tier in required})
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
