"""The human-labelled holdout: a labelled-set format, and the reports that calibrate bands on it.

F-6f6fc50e. The shipped calibration file says in its own ``calibrated_on`` field that its
numbers are a GENERIC SEED and not a real human-labelled holdout, and instructs the reader to
recalibrate against 50-100 labelled examples per check_type before any canon bind.
``thresholds``'s module docstring says the same, and records that an earlier docstring falsely
claimed otherwise. So every band number the product ships is an admitted placeholder, the
instruction for fixing that is printed inside the artifact -- and there was no format, no report
and no verb to carry it out. Grepped at the time of the finding: the only matches for holdout /
labelled / ground-truth / agreement anywhere in the package were the docstrings saying the
tooling does not exist.

THE FORMAT (the seam between this package and whichever domain produces images and scores).
A manifest is JSONL, one object per row, fields exactly ``image`` / ``contract`` / ``atom`` /
``label``, where a label is ``present`` / ``absent`` / ``borderline``. The SCORED companion is
that row plus ``score`` and ``band_key``, as emitted after a verifier pass. Two files rather
than one because they are produced by different actors at different times: a human writes the
first, an instrument writes the second, and a loader that accepted either could not tell an
unlabelled row from an unscored one. Both are read here with per-ROW refusals -- the whole
reason to use one line per record is that a defect has an address.

WHY THERE IS NO POLARITY FIELD, which looks like an omission and is not. A human label is about
PRESENCE: the atom's content is in the image, or it is not. Polarity is a property of the
CONTRACT (a ``must_not`` atom asks the same presence question and inverts the answer), so it
belongs at the gate, not in the labelled set. Fitting a band on presence and inverting at grade
time is one calibration serving both directions; carrying polarity here would invite fitting two.

WHAT THIS MAY AND MAY NOT DO. It RECOMMENDS. Band values are data, not interface (STABILITY.md
puts them under "not covered"), so nothing here writes a calibration table, constructs one, or
edits one -- a report that could write the file would turn a recommendation into a decision
nobody made. It READS receipts and never re-stamps one. It runs on SCORES, never on pixels, so
this module is GPU-free by construction: producing the scores live is the operator's act, with
the image extra installed, through the verifiers that already exist.

WHERE THE CALIBRATION HAPPENS. Scoring a labelled corpus is expensive and happens ONCE. Every
candidate table after that is arithmetic over a list of floats, through the same ``zone_shift``
comparison the offline re-grade is built on (``core.gate.regrade``) -- which is what makes
``sweep`` a sweep rather than N runs of a gate.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Final, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...errors import PromptCraftError
from ..contract.compile_questions import Polarity
from ..receipt.asset_record import AssetRecord
from .regrade import zone_shift
from .thresholds import Band, ThresholdTable, Zone
from .thresholds import _describe as _describe_validation_error


class Label(StrEnum):
    """What a human said about one atom in one image.

    Three values, not two. ``borderline`` is the whole reason a band has a middle: a two-valued
    holdout can fit a single cut point, and a single cut point cannot express "this one is a
    human's call", which is the band this gate routes to a checkpoint.
    """

    present = "present"
    absent = "absent"
    borderline = "borderline"


class HoldoutRow(BaseModel):
    """One human judgement. ``contract`` and ``atom`` are free strings by design -- this format
    knows nothing about any particular domain's ids, and must not become a claim about one."""

    model_config = ConfigDict(extra="forbid")
    image: str = Field(min_length=1)
    contract: str = Field(min_length=1)
    atom: str = Field(min_length=1)
    label: Label


class ScoredRow(HoldoutRow):
    """A manifest row after an instrument scored it.

    ``band_key`` is carried rather than re-derived because it is the answer to "which
    calibration graded this number", and on a routed gate that is NOT the same as the atom's
    declared check_type -- the same fact ``AtomVerdict.band_key`` exists to record.
    """

    score: float = Field(ge=0.0, le=1.0)
    band_key: str = Field(min_length=1)


MANIFEST_FIELDS: Final[tuple[str, ...]] = tuple(HoldoutRow.model_fields)
"""The seam, derived from the model so the two cannot drift apart."""

SCORED_FIELDS: Final[tuple[str, ...]] = tuple(ScoredRow.model_fields)

_LABEL_POLARITY: Final[Polarity] = Polarity.affirm
"""A label is read in the affirm direction. See "WHY THERE IS NO POLARITY FIELD" above."""

EXPECTED_ZONE: Final[dict[Label, Zone]] = {
    Label.present: Zone.PASS,
    Label.absent: Zone.FAIL,
    Label.borderline: Zone.UNCERTAIN,
}
"""What a well-calibrated band does with each label. This mapping IS the agreement criterion."""


# --------------------------------------------------------------------------------------
# the two files
# --------------------------------------------------------------------------------------


_Row = TypeVar("_Row", bound=HoldoutRow)


def _read_rows(path: str | Path, model: type[_Row], what: str) -> list[_Row]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as err:
        raise PromptCraftError(
            "IO_HOLDOUT_READ", f"could not read {what} {p}: {err.strerror or err}", cause=err
        ) from err
    rows: list[_Row] = []
    # The PHYSICAL line number, blanks included: it is the address the operator opens their
    # editor at. A count of non-blank rows would be a different number from the one their
    # editor shows, which is the one thing this refusal exists to give them.
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as err:
            raise PromptCraftError(
                "INPUT_HOLDOUT_ROW",
                f"{what} {p} row {n} is not valid JSON ({err})",
                cause=err,
            ) from err
        if not isinstance(data, dict):
            raise PromptCraftError(
                "INPUT_HOLDOUT_ROW",
                f"{what} {p} row {n} is valid JSON but not an object; each row is one record "
                f"with fields {', '.join(model.model_fields)}",
            )
        try:
            rows.append(model.model_validate(data))
        except ValidationError as err:
            raise PromptCraftError(
                "INPUT_HOLDOUT_ROW",
                f"{what} {p} row {n} {_describe_validation_error(err, 'holdout row')}",
                cause=err,
            ) from err
    if not rows:
        raise PromptCraftError(
            "INPUT_HOLDOUT_EMPTY",
            f"{what} {p} contains no rows, so there is nothing to calibrate against",
        )
    return rows


def load_manifest(path: str | Path) -> list[HoldoutRow]:
    """Read a labelled manifest. One object per line; every field required, no extras."""
    return _read_rows(path, HoldoutRow, "holdout manifest")


def load_scored(path: str | Path) -> list[ScoredRow]:
    """Read the scored companion. A manifest read through here is a refusal, not a guess: a row
    with no score is a row nothing has measured yet, and treating it as one would be an
    invention."""
    return _read_rows(path, ScoredRow, "scored holdout")


def dump_scored(rows: Iterable[ScoredRow]) -> str:
    """The scored companion as JSONL text. LF endings, one record per line, trailing newline."""
    return "".join(row.model_dump_json() + "\n" for row in rows)


def write_scored(rows: Iterable[ScoredRow], path: str | Path) -> Path:
    """Write the scored companion.

    Truncating, unlike the receipt writer: a scored set is DERIVED data -- re-emit it whenever
    the verifier checkpoint moves. The receipt's no-overwrite rule protects an audit trail of a
    decision that was made; nothing here is a decision.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump_scored(rows), encoding="utf-8", newline="\n")
    return p


# --------------------------------------------------------------------------------------
# the records source: scores that already exist on disk
# --------------------------------------------------------------------------------------


class ScoringPass(BaseModel):
    """What a labelled set looks like after it meets the receipts.

    ``unscored`` is not an error and not padding: it is the list of labelled rows no receipt has
    a number for. Reporting it is what stops a corpus from silently shrinking to whatever
    happened to be bound, which would make every report below quietly answer a smaller question
    than the one it was asked.
    """

    model_config = ConfigDict(extra="forbid")
    scored: list[ScoredRow] = Field(default_factory=list)
    unscored: list[HoldoutRow] = Field(default_factory=list)


def _norm(image: str) -> str:
    return Path(image).expanduser().as_posix()


def scored_from_records(
    rows: Sequence[HoldoutRow], records: Iterable[AssetRecord]
) -> ScoringPass:
    """Join labelled rows to scores already on disk. Pure read; no record is modified.

    The join key is (image, contract, atom). Images are matched on the normalised path first;
    when that finds nothing, the file NAME is tried -- a manifest is often written on a machine
    other than the one that bound the assets -- but only when exactly one record carries that
    name for the same contract and atom. An ambiguous name is left UNSCORED rather than resolved
    by a guess, which is the whole difference between a join and a coincidence.

    A verdict with no score, or with no band key, cannot place a row on a band, so its row is
    unscored too. The gate never measured it; nothing here can.
    """
    exact: dict[tuple[str, str, str], tuple[float, str]] = {}
    by_name: dict[tuple[str, str, str], list[tuple[float, str]]] = {}
    for record in records:
        for v in record.gate_transcript.verdicts:
            if v.score is None or not v.band_key:
                continue
            value = (v.score, v.band_key)
            exact.setdefault((_norm(record.image_path), record.contract_id, v.atom_id), value)
            by_name.setdefault(
                (Path(record.image_path).name, record.contract_id, v.atom_id), []
            ).append(value)

    out = ScoringPass()
    for row in rows:
        hit = exact.get((_norm(row.image), row.contract, row.atom))
        if hit is None:
            named = by_name.get((Path(row.image).name, row.contract, row.atom), [])
            hit = named[0] if len(named) == 1 else None
        if hit is None:
            out.unscored.append(row)
            continue
        score, band_key = hit
        out.scored.append(
            ScoredRow(
                image=row.image, contract=row.contract, atom=row.atom, label=row.label,
                score=score, band_key=band_key,
            )
        )
    return out


# --------------------------------------------------------------------------------------
# the separation report: what the humans said, and where a band would have to sit
# --------------------------------------------------------------------------------------


class LabelStats(BaseModel):
    """One label class on one band. Five numbers, because a mean would hide the tails and the
    tails are what a band is fitted to."""

    model_config = ConfigDict(extra="forbid")
    label: Label
    n: int
    lo: float
    p50: float
    hi: float


class BandSeparation(BaseModel):
    """One band key's holdout: the distributions, whether they separate, and the fitted band."""

    model_config = ConfigDict(extra="forbid")
    band_key: str
    n: int
    counts: dict[str, int]
    classes: list[LabelStats] = Field(default_factory=list)
    """Only label classes that have rows. An empty class has no lo/p50/hi to state, and a row of
    nulls is not a statistic."""
    separates: bool
    recommended: Band | None = None
    """The fitted band, ABSENT when the classes overlap. Never written anywhere by this module."""
    overlap: str = ""
    """Why there is no recommendation, when there is none."""
    borderline_outside: list[str] = Field(default_factory=list)
    """Images the humans called borderline that the recommended band would decide anyway."""

    def to_dict(self) -> dict:
        """JSON-ready, with absent keys OMITTED rather than emitted as null."""
        return self.model_dump(mode="json", exclude_none=True)


class SeparationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: int
    bands: list[BandSeparation] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


def _stats(label: Label, scores: list[float]) -> LabelStats:
    ordered = sorted(scores)
    return LabelStats(
        label=label,
        n=len(ordered),
        lo=ordered[0],
        p50=statistics.median(ordered),
        hi=ordered[-1],
    )


def recommend_band(present: Sequence[float], absent: Sequence[float]) -> Band | None:
    """The widest band that puts every ``present`` in PASS and every ``absent`` in FAIL.

    ``high = min(present)``, ``low = max(absent)``, and only when the classes actually separate.
    Deliberately the simplest rule that can be checked by eye against the printed distributions:
    an operator has to be able to see WHY these two numbers, because they are about to become
    the numbers a gate blocks a bind on. A quantile rule would be more robust to one mislabelled
    row and less explicable, which is the wrong trade for a recommendation a human must approve.

    Returns ``None`` when the classes overlap -- there is no such band, and inventing one by
    splitting the difference would be this module making up calibration.
    """
    if not present or not absent:
        return None
    high, low = min(present), max(absent)
    if low >= high:
        return None
    return Band(high=high, low=low)


def separation_report(rows: Sequence[ScoredRow]) -> SeparationReport:
    """Per band key: what each label class scored, and the band that would separate them."""
    by_band: dict[str, list[ScoredRow]] = {}
    for row in rows:
        by_band.setdefault(row.band_key, []).append(row)

    bands: list[BandSeparation] = []
    for band_key in sorted(by_band):
        group = by_band[band_key]
        scores = {label: [r.score for r in group if r.label is label] for label in Label}
        recommended = recommend_band(scores[Label.present], scores[Label.absent])
        outside = (
            [
                r.image
                for r in group
                if r.label is Label.borderline
                and not (recommended.low < r.score < recommended.high)
            ]
            if recommended is not None
            else []
        )
        bands.append(
            BandSeparation(
                band_key=band_key,
                n=len(group),
                counts={label.value: len(scores[label]) for label in Label},
                classes=[_stats(label, scores[label]) for label in Label if scores[label]],
                separates=recommended is not None,
                recommended=recommended,
                overlap="" if recommended is not None else _why_no_band(scores),
                borderline_outside=outside,
            )
        )
    return SeparationReport(rows=len(rows), bands=bands)


def _why_no_band(scores: dict[Label, list[float]]) -> str:
    present, absent = scores[Label.present], scores[Label.absent]
    if not present or not absent:
        return (
            f"fitting a band needs both classes; this one has {len(present)} 'present' and "
            f"{len(absent)} 'absent' row(s)"
        )
    return (
        f"an 'absent' row scores {max(absent)} while a 'present' row scores {min(present)}, so "
        f"no single band puts every 'present' in PASS and every 'absent' in FAIL"
    )


# --------------------------------------------------------------------------------------
# the agreement report: what a candidate table would do with these labels
# --------------------------------------------------------------------------------------


class BandAgreement(BaseModel):
    """One band's disagreement map. Four named classes, because they are four different problems.

    A single accuracy number would average the one that matters into the ones that do not:
    ``absent_but_pass`` is the gate confidently accepting something a human says is not there,
    which is the failure a verifier exists to prevent.
    """

    model_config = ConfigDict(extra="forbid")
    band_key: str
    n: int
    agree: int
    absent_but_pass: list[ScoredRow] = Field(default_factory=list)
    """The human said absent; the table says PASS. Confident acceptance of a miss."""
    present_but_fail: list[ScoredRow] = Field(default_factory=list)
    """The human said present; the table says FAIL. Confident rejection of a hit."""
    unconfirmed: list[ScoredRow] = Field(default_factory=list)
    """The human was sure and the table is not -- routed to a checkpoint. Cost, not danger."""
    overconfident: list[ScoredRow] = Field(default_factory=list)
    """The human called it borderline and the table decided it anyway."""

    @property
    def rate(self) -> float:
        return self.agree / self.n if self.n else 0.0


class AgreementReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    fingerprint: str
    """The table's values-hash -- the same string a replay drift refusal quotes, so an agreement
    number can be tied to the exact numbers that produced it."""
    rows: int
    agree: int
    bands: list[BandAgreement] = Field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.agree / self.rows if self.rows else 0.0

    def to_dict(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


def agreement(rows: Sequence[ScoredRow], table: ThresholdTable) -> AgreementReport:
    """How ``table`` grades these labelled rows against what the humans said."""
    by_band: dict[str, list[ScoredRow]] = {}
    for row in rows:
        by_band.setdefault(row.band_key, []).append(row)

    bands: list[BandAgreement] = []
    for band_key in sorted(by_band):
        group = by_band[band_key]
        band = BandAgreement(band_key=band_key, n=len(group), agree=0)
        for row in group:
            zone = table.zone(row.band_key, row.score, _LABEL_POLARITY)
            if zone is EXPECTED_ZONE[row.label]:
                band.agree += 1
            elif row.label is Label.absent and zone is Zone.PASS:
                band.absent_but_pass.append(row)
            elif row.label is Label.present and zone is Zone.FAIL:
                band.present_but_fail.append(row)
            elif row.label is Label.borderline:
                band.overconfident.append(row)
            else:
                band.unconfirmed.append(row)
        bands.append(band)
    return AgreementReport(
        version=table.version,
        fingerprint=table.fingerprint(),
        rows=len(rows),
        agree=sum(b.agree for b in bands),
        bands=bands,
    )


# --------------------------------------------------------------------------------------
# the sweep: N candidate tables, zero verifier runs
# --------------------------------------------------------------------------------------


class SweepEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str
    fingerprint: str
    rows: int
    agree: int
    absent_but_pass: int
    present_but_fail: int
    flips: int
    """Rows whose ZONE differs from the zone the same row gets under the baseline. A different
    question from ``agree``, which is about the humans -- a candidate can move many rows and
    agree no better, and that is exactly the thing worth seeing before a retune ships."""

    @property
    def rate(self) -> float:
        return self.agree / self.rows if self.rows else 0.0

    def to_dict(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


def sweep(
    rows: Sequence[ScoredRow],
    candidates: Mapping[str, ThresholdTable],
    *,
    baseline: ThresholdTable | None = None,
) -> list[SweepEntry]:
    """Rank candidate tables over one labelled corpus. Best agreement first.

    No verifier runs and no pixels are read: a scored corpus is a list of floats, and each
    candidate is one pass over it. ``flips`` is measured through ``regrade.zone_shift`` -- the
    same comparison the offline receipt re-grade makes -- so "what moved" means one thing across
    both surfaces. With no ``baseline`` there is no before, so every entry reports 0 flips and
    the result is an agreement ranking rather than a change report.

    Ties break on fewer confident-acceptance errors, then on name, so the order is deterministic.
    """
    entries: list[SweepEntry] = []
    for name in sorted(candidates):
        table = candidates[name]
        report = agreement(rows, table)
        flips = 0
        if baseline is not None:
            flips = sum(
                zone_shift(
                    baseline.zone(row.band_key, row.score, _LABEL_POLARITY),
                    row.band_key,
                    row.score,
                    _LABEL_POLARITY,
                    table,
                ).flipped
                for row in rows
            )
        entries.append(
            SweepEntry(
                name=name,
                version=table.version,
                fingerprint=table.fingerprint(),
                rows=report.rows,
                agree=report.agree,
                absent_but_pass=sum(len(b.absent_but_pass) for b in report.bands),
                present_but_fail=sum(len(b.present_but_fail) for b in report.bands),
                flips=flips,
            )
        )
    entries.sort(key=lambda e: (-e.agree, e.absent_but_pass, e.name))
    return entries


__all__ = [
    "EXPECTED_ZONE",
    "MANIFEST_FIELDS",
    "SCORED_FIELDS",
    "AgreementReport",
    "BandAgreement",
    "BandSeparation",
    "HoldoutRow",
    "Label",
    "LabelStats",
    "ScoredRow",
    "ScoringPass",
    "SeparationReport",
    "SweepEntry",
    "agreement",
    "dump_scored",
    "load_manifest",
    "load_scored",
    "recommend_band",
    "scored_from_records",
    "separation_report",
    "sweep",
    "write_scored",
]
