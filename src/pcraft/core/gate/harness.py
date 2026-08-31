"""The gate harness: run a tiered set of Verifiers over the question DAG, dependency-ordered.

Routing is cheapest-decides-first: ``siglip2``/``palette`` atoms hit the Tier-0 screen; ``vqa`` atoms
hit Tier-1 (VQAScore); a Tier-1 UNCERTAIN/FAIL escalates to Tier-2 (DSG) for per-atom localization.
Evaluation is parent-first: a non-passing parent forces its children to N/A (a NO parent forces NO on
descendants), and a ``depends_on`` naming no atom in this contract is SKIPPED, not treated as an atom
with no parent. A ``depends_on`` cycle has no parent-first order at all, so it is a coded refusal
(``CONTRACT_CYCLIC_DEPENDS_ON``, exit 1) rather than a gate result. A required atom that cannot be
confirmed (SKIPPED / NA / UNCERTAIN) never rolls up to a silent PASS -- it routes the whole asset to
the UNCERTAIN (human) band."""

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
    band_key: str = ""
    """Which calibration band graded ``score``. Empty when nothing scored.

    F-00cfd3f8: this was never recorded because it was never in doubt -- the zone came from
    ``thresholds.zone(q.check_type.value, ...)``, keyed purely by the atom's DECLARED check_type,
    with no relationship to which instrument produced the number. That assumption broke the moment
    a Tier-0 router began delegating: a ``palette`` atom whose enum carries no hex colours falls
    through to SigLIP2, whose scale is almost an order of magnitude away from the palette band
    (siglip2 high 0.10 / low 0.01 vs palette high 0.85 / low 0.50), so a confident SigLIP2 match
    read as a confident palette FAIL. Which band graded the number is now an answer on the
    transcript rather than something a reader has to re-derive from the check_type."""
    detail: str | None = None
    """What the instrument saw, in its own terms, when it can say (coordinator addition).

    A score is one number and the band says which side of the line it fell on; neither says WHY.
    The image domain's Tier-0 router knows which colours of the declared palette it did and did
    not hit, and the Tier-2 localizer knows where it looked -- and none of that could reach a
    reader, because this model is ``extra="forbid"`` and ``evaluate`` composes ``reason`` itself,
    so a verifier had no channel to the transcript wider than a float.

    Optional and absent-by-default, which is the whole compatibility story: a verifier that
    exposes nothing leaves this ``None``, and every existing transcript, receipt and rendered
    line stays byte-for-byte what it was. ``AtomVerdict`` is not a name STABILITY.md covers (that
    row promises ``GateTranscript`` and the ``Verifier`` protocol), and an optional defaulted
    field is additive under ``extra="forbid"`` in both directions regardless -- the same rule
    ``AssetRecord``'s F-f99c78f8 fields established.

    A string, not a structure: this field exists to be READ. A verifier that answers with a
    mapping is rendered into one at the seam (``_detail_for``) rather than pushing an untyped
    dict onto a model whose every other field is typed."""
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

    def required_atoms(self) -> list[AtomVerdict]:
        """Every atom the gate is allowed to block on -- the denominator of "n of m scored".

        F-56203d3d: ``scored_required`` was the only way to ask how many required atoms produced
        a number, and nothing published the total to compare it against, so ``exit_contract``
        could not say "1 of 6 required atoms scored" without re-deriving ``_counts`` for itself.
        One definition of "required", one place."""
        return [v for v in self.verdicts if _counts(v)]

    def scored_required(self) -> list[AtomVerdict]:
        """Required / must_not atoms that produced a numeric score."""
        return [v for v in self.verdicts if _counts(v) and v.score is not None]

    def declares_no_required_atom(self) -> bool:
        """This contract has nothing the gate is allowed to block on.

        F-2c7b997a: ``could_not_run()`` merged this with "no required atom produced a score" and
        only the second is a could-not-run. MEASURED through ``sample.run_mock_loop`` with every
        atom's severity set to optional: all ten atoms scored and all ten passed, and the run
        still reported ``GATE_UNAVAILABLE`` at exit 4 -- whose hint tells the operator to
        "Install the [image] extra ... so a verifier can score", advice for a run in which every
        verifier scored. Fail-closed is right (nothing binds either way); the DIAGNOSIS was
        wrong, and it pointed at a repair that has no bearing on the actual defect, which is in
        the contract.
        """
        return not any(_counts(v) for v in self.verdicts)

    def could_not_run(self) -> bool:
        """A required atom exists and none of them produced a score. Distinct from
        UNCERTAIN-after-a-score, and (since F-2c7b997a) distinct from a contract that declares no
        required atom at all -- see ``declares_no_required_atom``."""
        return not self.declares_no_required_atom() and not self.scored_required()


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

    # --- The DAG really is acyclic, or this is a refusal and not a gate result (F-2b317b56).
    # depends_on referential integrity used to be closed in ONE direction: the loader refuses a
    # parent that does not exist and the branch below fails closed with SKIPPED, but nothing on
    # this path ever asked whether the surviving edges are ACYCLIC. The acyclicity check lives
    # in QuestionDAG.topological() as a bare ``raise ValueError``, an exception from outside the
    # PromptCraftError hierarchy, and this call site was unguarded -- in deliberate contrast to
    # ``_safe_score`` below, which is careful to classify every exception a verifier can throw.
    # MEASURED before the fix, on a contract with tabard.depends_on='sigil' and
    # sigil.depends_on='tabard': ``pcraft bind --mock`` and ``pcraft gate <image>`` both died
    # with error[RUNTIME_UNEXPECTED] at exit 2 -- the backstop code -- on what is a plain
    # contract-authoring typo that the namespace table in errors.py puts at exit 1 with a
    # CONTRACT_ code. Same shape as F-45c39f7d (raw ValidationError) and F-84788251 (raw
    # KeyError), landing on the field this wave's own depends_on fix was about.
    #
    # REACHABILITY: this is the gate's own net. A load-time refusal belongs at the loader's
    # door and does not remove the need for this one -- a caller who constructs a QuestionDAG
    # directly rather than resolving a contract (the regression tests do exactly that) reaches
    # no loader at all, and a cyclic DAG must be an ANSWER here, never a bare ValueError and
    # never an unbounded walk.
    try:
        parent_first = dag.topological()
    except PromptCraftError:
        raise  # already coded (e.g. refused at the loader's door); do not re-wrap
    except (ValueError, RecursionError) as err:
        raise PromptCraftError(
            "CONTRACT_CYCLIC_DEPENDS_ON",
            f"contract {dag.contract_id!r} has a depends_on cycle, so no parent-first "
            f"evaluation order exists: {err}",
            cause=err,
        ) from err

    for q in parent_first:
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
            #
            # REACHABILITY (F-09f30018): this branch is defence in depth, not a live check, and
            # says so for the same reason retry_policy.verdict_from_transcript and
            # exit_contract's census branch now do -- a guard that does not state its status
            # reads as either dead code to delete or a live check to rely on, and a maintainer
            # cannot tell which. loader._reject_unknown_depends_on refuses a dangling parent at
            # resolve() time, so no shipped command reaches here; a caller who constructs a
            # QuestionDAG himself still can, and this is his net.
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

        used_id, used_tier, used_verifier = verifier.verifier_id, tier, verifier
        band_key = _band_key(q.check_type, used_id, thresholds)
        zone = thresholds.zone(band_key, score, q.polarity)
        tiers_consulted = [tier]

        # Escalate a borderline/failed Tier-1 result to Tier-2 (DSG) for localization.
        if tier == 1 and zone in (Zone.UNCERTAIN, Zone.FAIL) and 2 in verifiers:
            score2, _skip2 = _safe_score(verifiers[2], image_path, q)
            if score2 is not None:
                used_id, used_tier, used_verifier = verifiers[2].verifier_id, 2, verifiers[2]
                band_key = _band_key(q.check_type, used_id, thresholds)
                score, zone = score2, thresholds.zone(band_key, score2, q.polarity)
                # ⚑ CORRECTED IN PLACE (F-d9b28ca6). used_tier used to be overwritten with no
                # record that Tier-1 ran first -- Tier-1's UNCERTAIN/FAIL score is what
                # triggered this escalation, so it necessarily ran. tier_used keeps meaning
                # "the tier whose score decided the verdict"; tiers_consulted is the separate,
                # additive fact the census actually needs: every tier that produced a real
                # score for this atom, escalated or not.
                tiers_consulted.append(2)

        # F-b1b29cef: the band's NUMBERS travel with its name. ``band_key`` alone told a reader
        # WHICH instrument's calibration graded the score (F-00cfd3f8, for attribution) but not
        # what that calibration IS -- and the shipped table's outermost pair is fifty times apart
        # (palette 0.85/0.50 vs siglip2 0.10/0.01), so a bare float in a shared column cannot be
        # read. MEASURED, real ``pcraft gate``: ``[FAIL] palette 0.333`` printed above
        # ``[PASS] no_rival_colours 0.005``. Stating it HERE rather than in a renderer is what
        # puts it on every surface that prints a verdict line -- the CLI transcript, the receipt
        # that stores this reason, and any consumer of the transcript model -- from one place,
        # and ``Band.describe`` reads the band in the direction this atom is actually asked.
        band = thresholds.band_for(band_key)
        verdicts[q.atom_id] = AtomVerdict(
            atom_id=q.atom_id, polarity=q.polarity, severity=q.severity,
            score=round(score, 4), zone=zone, tier_used=used_tier, tiers_consulted=tiers_consulted,
            verifier_id=used_id, band_key=band_key,
            detail=_detail_for(used_verifier, image_path, q),
            reason=f"score {score:.4f} -> {zone.value} "
            f"(band {band_key}: {band.describe(q.polarity)})",
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


_DETAIL_METHODS = ("score_detail", "localization_detail")
"""Optional members a verifier MAY expose to explain the score it just returned.

Not added to the ``Verifier`` protocol, which STABILITY.md covers: making these required would
break every verifier that does not have them, and making them protocol-optional is exactly what
duck-typing already expresses. A verifier that has neither is the normal case."""


def _detail_for(verifier, image_path: str, question: Question) -> str | None:
    """Ask the deciding instrument what it saw. Never let the answer break a gate.

    Coordinator addition, completing the image domain's half: ``Tier0Router.score_detail`` (a
    per-colour hit breakdown) and ``DSGVerifier.localization_detail`` produce facts that had no
    route to the transcript, because ``AtomVerdict`` is ``extra="forbid"`` and this function's
    caller composes ``reason`` itself.

    Three properties, each earned by a sibling in this file. It is OPTIONAL -- the method is
    looked up by name and its absence is the normal case, not an error. It is SAFE -- a detail
    method that raises must not turn a scored atom into a SKIPPED one or a crash, because this is
    commentary on a score that has already been computed, so the whole call is guarded the way
    ``_safe_score`` guards scoring. And it is TOLERANT of the two plausible signatures (mirroring
    ``score(image_path, question)``, or taking nothing because it describes the call just made),
    because the implementations live in another package and one wrong guess here would silently
    drop the field rather than fail loudly.

    A mapping is rendered to ``k=v`` pairs rather than stored raw: the field is a string because
    it exists to be read on a verdict line.
    """
    for name in _DETAIL_METHODS:
        method = getattr(verifier, name, None)
        if not callable(method):
            continue
        try:
            try:
                value = method(image_path, question)
            except TypeError:
                value = method()
        except Exception:  # noqa: BLE001 - commentary on an existing score; never a verdict
            return None
        rendered = _render_detail(value)
        if rendered:
            return rendered
    return None


def _render_detail(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return ", ".join(f"{k}={value[k]}" for k in sorted(value, key=str)) or None
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(x) for x in value) or None
    return str(value) or None


def _band_key(check_type: CheckType, verifier_id: str | None, thresholds: ThresholdTable) -> str:
    """Which band grades this number: the one belonging to the instrument that produced it.

    F-00cfd3f8 (this domain's half). Zoning was keyed on ``q.check_type`` alone, which assumes the
    atom's declared check_type also names the instrument. A Tier-0 ROUTER breaks that assumption
    without any signature changing: ``Tier0Router.score`` sends a ``palette`` atom whose enum
    carries no hex colours on to SigLIP2 (its own docstring says text enums "belong to SigLIP2"),
    and the SigLIP2 number was then graded against the palette band. Those bands are almost an
    order of magnitude apart, so the result is a CONFIDENT WRONG verdict, not an unconfirmed one --
    the same class of defect ``_pick``'s F-175c3b3e fix removed from the tier-fallback door, coming
    back through the delegation door.

    The agreement with the router is the value it already publishes: ``verifier_id`` is "who
    produced the score I just returned" (F-64b4f422), and this package names instruments
    ``<family>.<role>.<version>`` -- ``siglip2.screen.v1``, ``palette.hist.v1``. So the leading
    segment is the band family. No cross-import into ``domains/`` and no new protocol member.

    Deliberately conservative in one direction: the redirect only fires when the leading segment
    names a band the table ACTUALLY DECLARES. ``scripted.siglip2.v0``, ``vqascore.clip-flant5.v1``
    and ``dsg.localizer.v1`` all lead with a segment that is not a band key, so they keep the
    atom's check_type -- inventing a band out of an arbitrary verifier_id, or falling to
    ``default``, would be a second silent re-scale wearing the first one's fix as a disguise.
    """
    declared = check_type.value
    if not verifier_id:
        return declared
    family = verifier_id.split(".", 1)[0]
    if family != declared and family in thresholds.bands:
        return family
    return declared


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

    A contract that declares NO required atom also lands on UNAVAILABLE here, and deliberately
    stays there (F-2c7b997a): the roll-up is a Zone, and there is no Zone that honestly means
    "there was nothing to decide", so it fails closed and nothing binds. What changed is that the
    Zone is no longer the whole answer -- ``GateTranscript.declares_no_required_atom`` states the
    cause, ``exit_contract`` answers ``CONTRACT_NO_REQUIRED_ATOM`` instead of telling the operator
    to install extras, and the checkpoint says which of the two it is.
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
