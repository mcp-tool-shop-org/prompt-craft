"""Offline re-grade: what a candidate threshold table WOULD have decided, on scores already taken.

F-dec37d4e. Retuning a band is a hand-edit of a calibration file, and the only feedback the
product gave was ``pcraft replay`` REFUSING: ``STATE_REPLAY_DRIFT`` says the table moved and
names neither an atom nor a direction. Every input needed to answer the real question is
already on the receipt -- per-atom ``score``, ``band_key``, ``polarity`` and ``severity`` on
each ``AtomVerdict`` inside ``gate_transcript`` -- and ``ThresholdTable.zone()`` is the exact
function that graded it the first time. MEASURED on a real receipt bound by
``sample.run_mock_loop``: a candidate moving vqa from 0.80/0.40 to 0.96/0.40 takes tabard,
sigil, skin, weapon and face from PASS to UNCERTAIN -- five blocking flips on an asset already
in canon. Zero GPU, zero regeneration, no new on-disk format.

Four properties this module is built to keep, each one a promise it would be easy to break:

READ-ONLY. Nothing here writes, re-stamps or migrates a receipt. ``schema_version: "1"`` is a
covered reader (STABILITY.md) and the whole value of a receipt is that it is the record of a
decision that was made, not a document that gets updated when the numbers move. Every
transformation below builds new objects; ``AssetRecord`` is never mutated and never persisted.

IT REPORTS, IT DOES NOT GATE. STABILITY.md puts threshold table VALUES under "not covered --
data, not interface", with the compensating guarantee that a decision cannot be silently
replayed under another table. That guarantee is ``replay``'s, and it is untouched: ``replay``
still raises ``STATE_REPLAY_DRIFT`` on the same table in the same run. This module is the READ
that turns that refusal into an answer, which is a different job from relaxing it.

ONE ROLL-UP, NOT TWO. The re-derived overall comes from ``harness._rollup`` and the re-derived
refusal from ``exit_contract.error_from_transcript`` -- the same two functions the live gate
uses, reached by building a real ``GateTranscript`` and handing it to them. A second roll-up
implementation would answer a slightly different question from the gate it claims to predict,
and would drift the first time either side was edited.

IT NEVER INVENTS A SCORE. An atom whose parent blocked it (NA) or whose verifier was absent
(SKIPPED) carries no number, so no table can move it. Those atoms are CARRIED, listed by name,
and excluded from every count. A re-grade can tell you a passing atom would become uncertain;
it cannot tell you what an atom the gate never scored would have done, and saying so is the
difference between a report and a confident invention.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..contract.compile_questions import Polarity, QuestionDAG, Severity
from ..receipt.asset_record import AssetRecord, receipt_paths
from ..receipt.asset_record import load as load_record
from .exit_contract import error_from_transcript

# ``_rollup`` and ``_tier_census`` are private to ``core.gate``, and that is exactly what is
# wanted here: this module is inside that package. Importing them is the whole point (see "ONE
# ROLL-UP, NOT TWO" above) -- a public re-export would only be a second name for one function,
# and a local copy would be the drift the finding's fourth must-not-break names.
from .harness import AtomVerdict, GateTranscript, _rollup, _tier_census, verdict_reason
from .thresholds import ThresholdTable, Zone


class ZoneShift(BaseModel):
    """One atom's verdict, before and after. The single comparison this feature is made of.

    Shared with the labelled-holdout sweep (``core.gate.holdout``), which asks the same question
    of a labelled row rather than of a receipt: "what was this, and what would it be". Keeping
    ONE implementation of the comparison is what stops the two surfaces from disagreeing about
    what a flip is.
    """

    model_config = ConfigDict(extra="forbid")
    was: Zone
    now: Zone

    @property
    def flipped(self) -> bool:
        return self.was is not self.now


def zone_shift(
    was: Zone,
    band_key: str,
    score: float,
    polarity: Polarity,
    candidate: ThresholdTable,
) -> ZoneShift:
    """Re-grade one score under ``candidate``, against the zone it already has.

    ``was`` is passed in rather than recomputed because the two callers know it differently: a
    receipt STORES the zone the gate assigned (the authoritative fact -- it is what was decided),
    while a table sweep derives it from a baseline table. Recomputing it here would quietly
    replace the receipt's own record of its decision with this build's opinion of it.
    """
    return ZoneShift(was=was, now=candidate.zone(band_key, score, polarity))


class AtomRegrade(BaseModel):
    """One scored atom under the candidate table."""

    model_config = ConfigDict(extra="forbid")
    atom_id: str
    band_key: str
    polarity: Polarity
    severity: Severity
    score: float
    was: Zone
    now: Zone

    @property
    def flipped(self) -> bool:
        return self.was is not self.now

    @property
    def blocking(self) -> bool:
        """Whether a flip here can move the gate's verdict.

        ``severity is required`` and nothing else -- the same rule ``harness._counts`` applies.
        A negation blocks when its severity says so, exactly like an affirmation.
        """
        return self.severity is Severity.required


class RegradeReport(BaseModel):
    """What one receipt would decide under one candidate table.

    ``was_code`` / ``now_code`` are the ``exit_contract`` refusal codes, and ``""`` means the
    exit contract answered PASS -- the same absent-is-empty-string convention the receipt
    already uses for ``thresholds_fingerprint`` and ``band_key``, so a JSON consumer never
    meets a null.
    """

    model_config = ConfigDict(extra="forbid")
    record_id: str
    contract_id: str
    decision: str
    """The receipt's own decision, quoted verbatim. A re-grade does not re-decide it."""
    from_version: str
    from_fingerprint: str
    """The band values the receipt was decided under. ``""`` for a receipt written before the
    field existed -- legacy, not a refusal; a re-grade reads scores and needs no fingerprint."""
    to_version: str
    to_fingerprint: str
    atoms: list[AtomRegrade]
    carried: list[str]
    """Atom ids that carry no score, in transcript order. No table can move them."""
    was_overall: Zone
    now_overall: Zone
    was_code: str
    now_code: str

    @property
    def flips(self) -> list[AtomRegrade]:
        return [a for a in self.atoms if a.flipped]

    @property
    def blocking_flips(self) -> list[AtomRegrade]:
        return [a for a in self.flips if a.blocking]

    def summary(self) -> str:
        """One line an operator can read, in the terms the finding asked the question in.

        ASCII only and no width assumptions: this is a library return value, and the surface
        that prints it owns the wrapping (``pcraft.errors``'s one convention)."""
        if not self.flips:
            head = f"no verdict moves under {self.to_version!r}"
        else:
            moves: dict[str, list[str]] = {}
            for a in self.flips:
                moves.setdefault(f"{a.was.value} -> {a.now.value}", []).append(a.atom_id)
            head = "; ".join(
                f"{', '.join(ids)}: {move}" for move, ids in moves.items()
            )
        tail = [f"{len(self.blocking_flips)} blocking flip(s)"]
        if self.was_overall is not self.now_overall:
            tail.append(f"overall {self.was_overall.value} -> {self.now_overall.value}")
        if self.carried:
            tail.append(f"{len(self.carried)} atom(s) carried (never scored)")
        return f"{head}. " + ", ".join(tail) + "."


def regrade_verdicts(
    verdicts: Sequence[AtomVerdict], candidate: ThresholdTable
) -> list[AtomVerdict]:
    """Re-zone every SCORED verdict under ``candidate``; carry the rest unchanged.

    The ``reason`` is recomposed through ``harness.verdict_reason`` rather than kept, because a
    verdict whose zone moved while its reason still quotes the old band is a transcript that
    contradicts itself on the one field a reader consults to ask why.

    A verdict with no score is returned as an equal copy, not re-zoned: NA and SKIPPED are
    statements about the RUN (a parent blocked this atom; the verifier was absent), and no
    change to a calibration table can make them false or true.
    """
    out: list[AtomVerdict] = []
    for v in verdicts:
        if v.score is None:
            out.append(v.model_copy(deep=True))
            continue
        shift = zone_shift(v.zone, v.band_key, v.score, v.polarity, candidate)
        band = candidate.band_for(v.band_key)
        out.append(
            v.model_copy(
                deep=True,
                update={
                    "zone": shift.now,
                    "reason": verdict_reason(v.score, shift.now, v.band_key, band, v.polarity),
                },
            )
        )
    return out


def regrade_transcript(
    transcript: GateTranscript,
    candidate: ThresholdTable,
    *,
    dag: QuestionDAG | None = None,
) -> GateTranscript:
    """The transcript the gate would have produced from these same scores under ``candidate``.

    ``dag`` is optional and additive. With it the tier census is RE-DERIVED through
    ``harness._tier_census`` -- which proves the claim that a table cannot change which tiers
    executed, instead of asserting it by copying the stored census. Without it (a caller holding
    a bare transcript) the stored census is carried, since re-zoning touches no
    ``tiers_consulted`` list.
    """
    verdicts = regrade_verdicts(transcript.verdicts, candidate)
    census = _tier_census(dag, verdicts) if dag is not None else transcript.tier_census
    return GateTranscript(
        contract_id=transcript.contract_id,
        overall=_rollup(verdicts),
        verdicts=verdicts,
        tier_census=census,
        thresholds_version=candidate.version,
        # F-8cfaf7ec: carried, not dropped. A candidate table can move a zone; it cannot change
        # which pixels were scored, and a re-graded transcript that had forgotten its own image
        # would be unable to answer the one question a corpus sweep is asked next -- which
        # render this row is about.
        image_path=transcript.image_path,
    )


def _code(transcript: GateTranscript) -> str:
    err = error_from_transcript(transcript)
    return "" if err is None else err.code


def regrade(record: AssetRecord, candidate: ThresholdTable) -> RegradeReport:
    """Apply ``candidate`` to the scores in ``record``. Pure read; ``record`` is not mutated."""
    rebuilt = regrade_transcript(record.gate_transcript, candidate, dag=record.question_dag)
    now_by_id = {v.atom_id: v for v in rebuilt.verdicts}
    atoms = [
        AtomRegrade(
            atom_id=v.atom_id,
            band_key=v.band_key,
            polarity=v.polarity,
            severity=v.severity,
            score=v.score,
            was=v.zone,
            now=now_by_id[v.atom_id].zone,
        )
        for v in record.gate_transcript.verdicts
        if v.score is not None
    ]
    return RegradeReport(
        record_id=record.record_id,
        contract_id=record.contract_id,
        decision=record.decision,
        from_version=record.thresholds_version,
        from_fingerprint=record.thresholds_fingerprint,
        to_version=candidate.version,
        to_fingerprint=candidate.fingerprint(),
        atoms=atoms,
        carried=[v.atom_id for v in record.gate_transcript.verdicts if v.score is None],
        was_overall=record.gate_transcript.overall,
        now_overall=rebuilt.overall,
        was_code=_code(record.gate_transcript),
        now_code=_code(rebuilt),
    )


def regrade_records(
    records: Iterable[AssetRecord], candidate: ThresholdTable
) -> list[RegradeReport]:
    """The corpus question. A retune is asked about a body of bound assets, not about one."""
    return [regrade(r, candidate) for r in records]


def regrade_dir(records_dir: str | Path, candidate: ThresholdTable) -> list[RegradeReport]:
    """Every receipt directly under ``records_dir``, in sorted order.

    The walk itself is ``asset_record.receipt_paths`` (F-b0e6dde7), which is where it belongs:
    ``persist`` owns the convention for what a receipt is called and where it lands, so the
    module that writes them owns the question of which files in a directory are them. This
    function had its own copy of the glob and the receipt index would have made a third.

    A file this cannot read is a REFUSAL, not a skip -- ``asset_record.load``'s coded errors
    propagate. Silently omitting an unreadable receipt would make the sweep's answer quietly
    incomplete, which is the failure mode a corpus report exists to prevent. That is a
    deliberate difference from the INDEX, which reports an unreadable receipt as a row and keeps
    going: a re-grade computes a number over a corpus and a missing member corrupts it, while a
    listing's whole job is to tell you what is in the directory, including the parts that do not
    load.
    """
    return regrade_records([load_record(p) for p in receipt_paths(records_dir)], candidate)


__all__ = [
    "AtomRegrade",
    "RegradeReport",
    "ZoneShift",
    "regrade",
    "regrade_dir",
    "regrade_records",
    "regrade_transcript",
    "regrade_verdicts",
    "zone_shift",
]
