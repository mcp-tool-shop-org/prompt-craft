"""Calibration harness: a labelled holdout in, a ``sprite.cal.v2`` threshold table out.

F-0f9a1f90. ``sprite.calibration.json`` says of ITSELF, in its own ``calibrated_on`` field:
"GENERIC SEED - not a real human-labelled holdout. Recalibrate against ~50-100 labelled sprites
per check_type before any canon bind", and its ``notes`` add "vqa/palette bands are placeholders".
``core/gate/thresholds.py`` repeats it. MEASURED: a grep for 'calibrat' across ``src/``,
``scripts/`` and ``tests/`` returned only READERS -- five ``--thresholds`` options, the loader, the
fingerprint, the replay assertion -- and 'holdout' returned exactly one hit, that sentence. So the
product printed the instruction inside the artifact and shipped no way to carry it out: the only
path to a calibrated table was hand-editing three float pairs.

WHAT THIS IS NOT. It is the holdout workflow ONLY. It does not wire the cross-view identity
sub-gate into the loop and must not -- the standing ruling that the sub-gate stays UNWIRED is
correct precisely because nothing has measured what its 0.55 / 0.05 should be. ``measure_subgate``
below reports those two numbers as a MEASUREMENT and stops there. Nothing in this module imports
the sub-gate: STABILITY.md says of it, verbatim, "Do not build on this module, do not import it."

WHAT IT NEVER DOES. It emits; it does not adopt. The shipped default stays ``sprite.cal.v1`` until
a Director ratifies a swap, ``write_table`` refuses the packaged path outright, and every receipt
on disk keeps replaying under the table that decided it. The holdout manifest and its images are
DATA: this takes a path and packages no corpus.

GPU-FREE by construction: it calls the verifiers it is handed and does nothing else. A band whose
verifier could not answer is reported UNMEASURED and left out of the emitted table -- never
defaulted, which would be an invented number wearing a measurement's clothes.
"""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .....core.contract.compile_questions import Question, compile_questions
from .....core.contract.loader import ContractStore
from .....core.gate.harness import _band_key
from .....core.gate.thresholds import Band, ThresholdTable, Zone, load_thresholds
from .....errors import PromptCraftError
from . import THRESHOLDS_PATH

LABEL_PRESENT = "present"
LABEL_ABSENT = "absent"
LABEL_BORDERLINE = "borderline"
LABELS = (LABEL_PRESENT, LABEL_ABSENT, LABEL_BORDERLINE)

CALIBRATION_VERSION = "sprite.cal.v2"
"""The CALIBRATION version of an emitted table -- data, a name for these numbers.

NOT the ``$schema``. That is the reader contract and it is carried through unchanged from the base
table, because nothing about the on-disk FORMAT changes here. Conflating the two is the F-3637b97f
defect, and emitting new numbers under the OLD calibration name is the F-154dd9b2 one: ``asset_record``
asserts both the version string and ``fingerprint()`` (a content hash of the band values) on replay,
so a retune under 'sprite.cal.v1' is the precise STATE_REPLAY_DRIFT arm measured as unrecoverable
by its own hint.
"""

HOLDOUT_LOADER_MODULE = "pcraft.core.gate.holdout"
"""The module that OWNS the labelled-holdout file format. This module is its consumer, not a
second reader of the same format.

The agreed row shape is ``{"image", "contract", "atom", "label"}`` with ``label`` in
``present | absent | borderline``, one JSON object per line. Everything below consumes rows in
that shape and never parses a file itself, so there is exactly one place the format can change.
"""

HOLDOUT_LOADER_NAMES = ("load_holdout", "load_manifest", "load_rows", "read_holdout")
"""Reader names this consumer knows, tried in order. A module that is present but exposes none of
them is refused BY NAME rather than guessed at."""

# Copied, deliberately, from ``identity_subgate``. Not imported: STABILITY.md excludes that module
# from every promise and says not to build on it or import it, and a calibration harness that took
# an import dependency on it would be doing exactly that. These two numbers are here to be COMPARED
# against a measurement, which is the one use that does not build on the module.
SHIPPED_SUBGATE_FLOOR = 0.55
SHIPPED_SUBGATE_MAX_VARIANCE = 0.05

_PROBE_KEY = "fit-probe"


class LabelCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    present: int = 0
    absent: int = 0
    borderline: int = 0
    skipped: int = 0  # the verifier returned no score for this row


class Distribution(BaseModel):
    """What one label class actually scored. The evidence behind a chosen boundary."""

    model_config = ConfigDict(extra="forbid")
    n: int
    min: float
    max: float
    mean: float


class ScoredRow(BaseModel):
    """One holdout row after an instrument answered it -- the scored companion's line.

    ``band_key`` is not decorative: it is the key the gate would call ``ThresholdTable.zone`` with
    for this atom and this instrument, taken from the harness's own rule. A band fitted under a key
    the gate never uses is a confidently wrong table, which is the class of defect this whole
    package exists to catch.
    """

    model_config = ConfigDict(extra="forbid")
    image: str
    contract: str
    atom: str
    label: str
    band_key: str
    verifier_id: str
    score: float | None = None
    skipped_reason: str = ""


class BandFit(BaseModel):
    """One band's calibration, with the evidence and the counts behind it.

    ``fitted=False`` is a first-class outcome, not an error: a band the holdout did not measure is
    reported unmeasured and left OUT of the emitted table. Defaulting it would put an invented
    number where a measurement is claimed.
    """

    model_config = ConfigDict(extra="forbid")
    band_key: str
    fitted: bool
    reason: str = ""
    high: float | None = None
    low: float | None = None
    separation: float | None = None  # min(present) - max(absent); negative means the classes overlap
    clean: bool = False
    misfits: int = 0  # present rows graded FAIL, plus absent rows graded PASS. UNCERTAIN is neither.
    borderline_in_band: int = 0  # borderline rows that landed in the UNCERTAIN zone, as they should
    counts: LabelCounts = Field(default_factory=LabelCounts)
    present: Distribution | None = None
    absent: Distribution | None = None
    verifier_ids: list[str] = Field(default_factory=list)


class SubGateMeasurement(BaseModel):
    """The cross-view identity numbers, MEASURED. Reported, never applied.

    ``wired`` is a constant False and is here to be read: this type exists so a future Director has
    a measurement to decide on, and its presence in a report is not a decision.
    """

    model_config = ConfigDict(extra="forbid")
    measured: bool
    groups: int = 0
    present_groups: int = 0
    measured_floor: float | None = None  # the lowest per-view similarity across same-identity groups
    measured_max_variance: float | None = None  # the largest cross-view variance among those groups
    shipped_floor: float = SHIPPED_SUBGATE_FLOOR
    shipped_max_variance: float = SHIPPED_SUBGATE_MAX_VARIANCE
    wired: bool = False
    reason: str = ""


class CalibrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: str = ""
    rows: int = 0
    scored: list[ScoredRow] = Field(default_factory=list)
    bands: list[BandFit] = Field(default_factory=list)
    table: ThresholdTable
    subgate: SubGateMeasurement | None = None


# --------------------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------------------


def _field(row: Any, name: str) -> Any:
    """Read one field from a holdout row, whatever shape the loader hands back.

    A mapping (a decoded JSONL line) and a model instance are both accepted on purpose: the format
    loader is core-gate-loop's half of this seam, and a consumer that insisted on ONE of the two
    would have to be edited the day that module lands. The KEYS are the seam; the container is not.
    """
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _require(row: Any, name: str, index: int) -> str:
    value = _field(row, name)
    if value in (None, ""):
        raise PromptCraftError(
            "INPUT_HOLDOUT_ROW",
            f"holdout row {index} has no {name!r}",
            hint="Each row is {\"image\", \"contract\", \"atom\", \"label\"}; label is one of "
            "present, absent, borderline. Every field is required.",
        )
    return str(value)


def load_manifest(path: str | Path) -> list[Any]:
    """Read a labelled-holdout manifest through the loader ``core.gate`` owns.

    Deliberately NOT a parser. The format has one reader in this package; this function locates it
    and refuses in the package's own shape if it is absent, rather than letting a bare ImportError
    reach the CLI backstop and be reported as RUNTIME_UNEXPECTED ("prompt-craft crashed") for what
    is a missing component.
    """
    try:
        module = importlib.import_module(HOLDOUT_LOADER_MODULE)
    except ImportError as err:
        raise PromptCraftError(
            "DEP_HOLDOUT_LOADER_MISSING",
            f"reading a labelled holdout needs {HOLDOUT_LOADER_MODULE}, which this build does "
            "not have",
            hint="The manifest format has one reader and this is its consumer. Call "
            "calibrate(rows=...) with rows already loaded, or install a build that ships "
            f"{HOLDOUT_LOADER_MODULE}.",
            cause=err,
        ) from err
    reader = next((getattr(module, n) for n in HOLDOUT_LOADER_NAMES if hasattr(module, n)), None)
    if reader is None:
        raise PromptCraftError(
            "DEP_HOLDOUT_LOADER_MISSING",
            f"{HOLDOUT_LOADER_MODULE} exposes none of {list(HOLDOUT_LOADER_NAMES)}",
            hint="This consumer looks the reader up by name so the two halves can land in either "
            "order. Add the reader under one of those names, or pass rows to calibrate() directly.",
        )
    return list(reader(Path(path)))


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------


def _guarded_score(verifier: Any, image: str, question: Question) -> tuple[float | None, str]:
    """Call ``verifier.score`` and reject anything the Verifier protocol does not promise.

    The protocol is public and says: a float in [0, 1], or ``None`` when this verifier cannot
    answer. Enforcing it here is not a second copy of gate policy -- it is the reason a calibration
    sweep cannot fit a boundary on a number the gate itself would have thrown away as SKIPPED.
    """
    try:
        raw = verifier.score(image, question)
    except PromptCraftError:
        raise  # a coded refusal from a verifier is a defect, not a missing score
    except Exception as err:  # noqa: BLE001 - unavailable, exactly as the harness treats it
        return None, f"{verifier.verifier_id} raised {type(err).__name__}"
    if raw is None:
        return None, f"{verifier.verifier_id} returned no score"
    value = float(raw)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return None, f"{verifier.verifier_id} returned {raw!r}, which is not a score in [0, 1]"
    return value, ""


def score_rows(
    rows: Iterable[Any],
    *,
    store: ContractStore,
    verifiers: Sequence[Any],
    base_table: ThresholdTable,
) -> list[ScoredRow]:
    """Run every supplied verifier over every holdout row. One ScoredRow per (row, verifier).

    Every instrument scores every row on purpose. A band can then be fitted from the instrument
    that will actually produce its numbers at gate time, and ``BandFit.verifier_ids`` names which
    instruments a band was fitted across -- because two instruments sharing one band key share one
    scale, and an operator has to be able to see when that happened.
    """
    if not verifiers:
        raise PromptCraftError(
            "INPUT_HOLDOUT_NO_VERIFIER",
            "a calibration sweep needs at least one verifier to run over the holdout",
            hint="Pass the verifiers the gate uses. A sweep with no instrument measures nothing.",
        )
    dags: dict[str, Any] = {}
    out: list[ScoredRow] = []
    for index, row in enumerate(rows):
        image = _require(row, "image", index)
        contract_id = _require(row, "contract", index)
        atom_id = _require(row, "atom", index)
        label = _require(row, "label", index)
        if label not in LABELS:
            raise PromptCraftError(
                "INPUT_HOLDOUT_LABEL",
                f"holdout row {index} labels {atom_id!r} {label!r}",
                hint=f"A human label is one of {list(LABELS)}. 'borderline' is the honest answer "
                "for a sample a human cannot call, and it is counted rather than fitted.",
            )
        if contract_id not in dags:
            dags[contract_id] = compile_questions(store.resolve(contract_id))
        question = dags[contract_id].by_id(atom_id)
        if question is None:
            raise PromptCraftError(
                "INPUT_HOLDOUT_ATOM",
                f"holdout row {index} names atom {atom_id!r}, which {contract_id!r} does not carry",
                hint="Label the atoms the contract declares. `pcraft validate --contract <id>` "
                "lists them. A label for an atom nobody checks calibrates nothing.",
            )
        for verifier in verifiers:
            score, reason = _guarded_score(verifier, image, question)
            out.append(
                ScoredRow(
                    image=image,
                    contract=contract_id,
                    atom=atom_id,
                    label=label,
                    band_key=_band_key(question.check_type, verifier.verifier_id, base_table),
                    verifier_id=verifier.verifier_id,
                    score=score,
                    skipped_reason=reason,
                )
            )
    return out


# --------------------------------------------------------------------------------------
# Band fitting
# --------------------------------------------------------------------------------------


def _distribution(scores: list[float]) -> Distribution | None:
    if not scores:
        return None
    return Distribution(
        n=len(scores),
        min=round(min(scores), 4),
        max=round(max(scores), 4),
        mean=round(sum(scores) / len(scores), 4),
    )


def _grader(band: Band):
    """Grade with the REAL function rather than a second copy of its comparisons.

    ``ThresholdTable.zone`` is what graded every score the gate ever graded; re-implementing
    ``>= high`` / ``<= low`` here to count misfits would be a private fork of the one rule this
    table exists to feed. Polarity is deliberately ``affirm`` throughout: a human label is about
    PRESENCE, and ``zone`` inverts for a negate probe -- so a band fitted on presence labels is the
    correct band for both directions, and grading the fit in the affirm reading is what keeps the
    counts meaning "did the instrument see it".
    """
    table = ThresholdTable(version=CALIBRATION_VERSION, bands={_PROBE_KEY: band}, default=band)
    return lambda score: table.zone(_PROBE_KEY, score)


def _misfits(band: Band, present: list[float], absent: list[float]) -> int:
    grade = _grader(band)
    wrong = sum(1 for s in present if grade(s) is Zone.FAIL)
    return wrong + sum(1 for s in absent if grade(s) is Zone.PASS)


def _overlap_split(present: list[float], absent: list[float]) -> float:
    """The single split point that grades the fewest rows backwards, when the classes overlap.

    An overlapping band has no honest UNCERTAIN zone -- every interval between the classes contains
    labelled rows of both kinds -- so ``high == low`` and the report says ``clean=False``. Ties go
    to the LOWEST candidate so the fit is deterministic and reproducible from the same corpus.
    """
    candidates = sorted({0.0, 1.0, *present, *absent})
    best = candidates[0]
    best_cost = None
    for candidate in candidates:
        band = Band(high=candidate, low=candidate)
        cost = _misfits(band, present, absent)
        if best_cost is None or cost < best_cost:
            best, best_cost = candidate, cost
    return best


def fit_band(band_key: str, scored: Sequence[ScoredRow]) -> BandFit:
    """Fit one band from its scored rows. Reports UNMEASURED rather than guessing.

    THE RULE, stated once: ``high = min(present)`` and ``low = max(absent)``. Every PRESENT sample
    then grades PASS, every ABSENT sample grades FAIL, and the UNCERTAIN zone between them is
    exactly the interval where the labelled corpus provides no evidence -- which is the interval
    that should route to a human. The measured separation IS the width of that zone.

    When the classes overlap there is no such interval, so a single split point is chosen and the
    fit is marked ``clean=False`` with the rows it grades backwards counted. That is a fit an
    operator can weigh; a wide invented band that hides the overlap is not.
    """
    counts = LabelCounts()
    present: list[float] = []
    absent: list[float] = []
    borderline: list[float] = []
    verifier_ids: list[str] = []
    for row in scored:
        if row.verifier_id not in verifier_ids:
            verifier_ids.append(row.verifier_id)
        if row.score is None:
            counts.skipped += 1
            continue
        if row.label == LABEL_PRESENT:
            counts.present += 1
            present.append(row.score)
        elif row.label == LABEL_ABSENT:
            counts.absent += 1
            absent.append(row.score)
        else:
            counts.borderline += 1
            borderline.append(row.score)

    base = BandFit(
        band_key=band_key,
        fitted=False,
        counts=counts,
        present=_distribution(present),
        absent=_distribution(absent),
        verifier_ids=sorted(verifier_ids),
    )
    if not present or not absent:
        missing = [
            name
            for name, values in ((LABEL_PRESENT, present), (LABEL_ABSENT, absent))
            if not values
        ]
        skipped_note = f" ({counts.skipped} row(s) SKIPPED: no score)" if counts.skipped else ""
        return base.model_copy(
            update={
                "reason": f"unmeasured: no scored {' and no scored '.join(missing)} "
                f"sample{skipped_note}"
            }
        )

    separation = round(min(present) - max(absent), 4)
    clean = min(present) > max(absent)
    if clean:
        band = Band(high=round(min(present), 4), low=round(max(absent), 4))
    else:
        split = round(_overlap_split(present, absent), 4)
        band = Band(high=split, low=split)
    grade = _grader(band)
    return base.model_copy(
        update={
            "fitted": True,
            "high": band.high,
            "low": band.low,
            "separation": separation,
            "clean": clean,
            "misfits": _misfits(band, present, absent),
            "borderline_in_band": sum(1 for s in borderline if grade(s) is Zone.UNCERTAIN),
            "reason": "clean split" if clean else "classes overlap; single split point",
        }
    )


def fit_bands(scored: Sequence[ScoredRow]) -> list[BandFit]:
    """One fit per band key present in the scored rows, in stable key order."""
    by_key: dict[str, list[ScoredRow]] = {}
    for row in scored:
        by_key.setdefault(row.band_key, []).append(row)
    return [fit_band(key, by_key[key]) for key in sorted(by_key)]


# --------------------------------------------------------------------------------------
# The emitted table
# --------------------------------------------------------------------------------------


def _calibrated_on(manifest: str, fits: Sequence[BandFit], rows: int) -> str:
    """The sentence that replaces 'GENERIC SEED - not a real human-labelled holdout'.

    Deterministic on purpose -- counts and names, no timestamp -- so two runs over the same corpus
    produce the same table and a diff between them means the DATA moved.
    """
    totals = LabelCounts(
        present=sum(f.counts.present for f in fits),
        absent=sum(f.counts.absent for f in fits),
        borderline=sum(f.counts.borderline for f in fits),
        skipped=sum(f.counts.skipped for f in fits),
    )
    fitted = [f.band_key for f in fits if f.fitted]
    unmeasured = [f.band_key for f in fits if not f.fitted]
    parts = [
        f"MEASURED on {rows} labelled row(s) from {manifest or '<rows supplied directly>'}",
        f"present={totals.present}, absent={totals.absent}, borderline={totals.borderline}, "
        f"skipped={totals.skipped}",
        f"bands fitted: {', '.join(fitted) or 'none'}",
    ]
    if unmeasured:
        parts.append(
            f"bands UNMEASURED and therefore absent from this table: {', '.join(unmeasured)}"
        )
    parts.append(
        "EMITTED, NOT ADOPTED: the shipped default stays sprite.cal.v1 until a Director ratifies "
        "the swap, and every receipt keeps replaying under the table that decided it"
    )
    return ". ".join(parts) + "."


def _notes(fits: Sequence[BandFit]) -> str:
    lines = []
    for fit in fits:
        if not fit.fitted:
            lines.append(f"{fit.band_key}: {fit.reason}")
            continue
        lines.append(
            f"{fit.band_key}: high={fit.high} low={fit.low} separation={fit.separation} "
            f"(present n={fit.counts.present}, absent n={fit.counts.absent}, "
            f"misfits={fit.misfits}, {'clean' if fit.clean else 'OVERLAPPING'})"
        )
    lines.append(
        "A band absent from this table was not measured by this holdout. It falls to `default`, "
        "which is carried forward unchanged from the base table and is NOT a measurement."
    )
    return " | ".join(lines)


def build_table(
    fits: Sequence[BandFit], *, base_table: ThresholdTable, manifest: str = "", rows: int = 0
) -> ThresholdTable:
    """Assemble the emitted table. New calibration version, unchanged reader contract.

    ``default`` is carried forward from the base table rather than fitted. A default band is by
    definition the band for instruments this corpus did not measure, so deriving it from the corpus
    would be a claim about instruments that were never in it.
    """
    bands: dict[str, Band] = {}
    for fit in fits:
        # ``fitted`` means exactly "high and low are set". Testing all three is what makes that
        # invariant readable to a typechecker as well as to a reader -- and an unfitted band is
        # dropped here rather than emitted at ``default``, which is the whole point.
        if fit.fitted and fit.high is not None and fit.low is not None:
            bands[fit.band_key] = Band(high=fit.high, low=fit.low)
    return ThresholdTable(
        **{"$schema": base_table.schema_id},
        version=CALIBRATION_VERSION,
        bands=bands,
        default=base_table.default,
        calibrated_on=_calibrated_on(manifest, fits, rows),
        notes=_notes(fits),
    )


def write_table(table: ThresholdTable, path: str | Path) -> Path:
    """Write an emitted table to a NEW file. Refuses the packaged calibration outright.

    MUST NEVER overwrite ``sprite.cal.v1`` in place. ``fingerprint()`` hashes the band VALUES and
    ``asset_record`` asserts BOTH the version string and that fingerprint on replay, so retuning
    under the old name is the STATE_REPLAY_DRIFT arm whose own hint cannot recover it: every
    receipt bound under the old numbers would refuse, with nothing on disk still holding them.
    """
    target = Path(path)
    if target.resolve() == Path(THRESHOLDS_PATH).resolve():
        raise PromptCraftError(
            "INPUT_CALIBRATION_TARGET",
            f"refusing to overwrite the packaged calibration {target}",
            hint="Emit to a NEW file and adopt it explicitly with --thresholds. A retune written "
            "over sprite.cal.v1 makes every receipt bound under the old numbers unreplayable, "
            "because the table that decided them no longer exists anywhere.",
        )
    if table.version == "sprite.cal.v1":
        raise PromptCraftError(
            "INPUT_CALIBRATION_TARGET",
            "refusing to write new band values under the calibration name 'sprite.cal.v1'",
            hint="New numbers get a new calibration version. The version names WHICH numbers "
            "these are; reusing it is the undeclared retune the fingerprint exists to catch.",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = table.model_dump(by_alias=True, exclude_none=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def write_scored(scored: Sequence[ScoredRow], path: str | Path) -> Path:
    """Write the scored companion: one JSON object per line, alongside the manifest it scores.

    An absent value is an ABSENT KEY, never ``null``: a row the verifier could not answer carries
    ``skipped_reason`` and no ``score`` at all, so a reader cannot mistake "no measurement" for
    "measured zero" -- the same distinction the gate draws between SKIPPED and FAIL.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in scored:
        payload = row.model_dump(exclude_none=True)
        if not payload.get("skipped_reason"):
            payload.pop("skipped_reason", None)
        lines.append(json.dumps(payload, sort_keys=True))
    # An empty sweep writes an EMPTY file, not a file containing one blank line: a reader of JSONL
    # would have to treat that blank line as a malformed record.
    target.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return target


# --------------------------------------------------------------------------------------
# The sub-gate half: MEASUREMENT ONLY
# --------------------------------------------------------------------------------------


def measure_subgate(groups: Iterable[Mapping[str, Any]]) -> SubGateMeasurement:
    """Measure what the cross-view identity floor and variance ceiling WOULD be. Wires nothing.

    Each group is one turnaround: ``{"label": present|absent, "similarities": {direction: cosine}}``.
    The similarities are supplied rather than computed -- producing them is a CLIP-I embedding pass,
    which is the operator's later act on a real corpus and has no business inside a GPU-free sweep.

    ``measured_floor`` is the lowest per-view similarity observed across same-identity groups (any
    floor above it would reject a turnaround a human called correct) and ``measured_max_variance``
    the largest cross-view variance among them. Both are reported beside the shipped 0.55 / 0.05 so
    the two can be compared. Neither is applied: ``wired`` is False, this module does not import the
    sub-gate, and whether to wire it remains a Director's decision that now has a number under it.
    """
    total = 0
    floors: list[float] = []
    variances: list[float] = []
    for group in groups:
        total += 1
        if str(group.get("label") or "") != LABEL_PRESENT:
            continue
        sims = [float(v) for v in (group.get("similarities") or {}).values()]
        if not sims:
            continue
        mean = sum(sims) / len(sims)
        floors.append(min(sims))
        variances.append(sum((s - mean) ** 2 for s in sims) / len(sims))
    if not floors:
        return SubGateMeasurement(
            measured=False,
            groups=total,
            present_groups=0,
            reason="unmeasured: no same-identity turnaround groups carrying per-view similarities",
        )
    return SubGateMeasurement(
        measured=True,
        groups=total,
        present_groups=len(floors),
        measured_floor=round(min(floors), 4),
        measured_max_variance=round(max(variances), 6),
        reason="MEASUREMENT ONLY -- reported for a future decision, applied to nothing",
    )


# --------------------------------------------------------------------------------------
# The command logic
# --------------------------------------------------------------------------------------


def calibrate(
    rows: Sequence[Any],
    *,
    store: ContractStore,
    verifiers: Sequence[Any],
    base_table: ThresholdTable | None = None,
    manifest: str = "",
    subgate_groups: Iterable[Mapping[str, Any]] | None = None,
) -> CalibrationResult:
    """Score a labelled holdout, fit its bands, and build the emitted table. Writes nothing.

    This is the whole verb minus its two file operations, so a CLI wrapper is the three lines that
    load the rows and write the two artifacts -- and so a Python caller with rows already in hand
    never has to touch the on-disk format at all.
    """
    table = base_table or load_thresholds(THRESHOLDS_PATH)
    scored = score_rows(rows, store=store, verifiers=verifiers, base_table=table)
    fits = fit_bands(scored)
    return CalibrationResult(
        manifest=manifest,
        rows=len(rows),
        scored=scored,
        bands=fits,
        table=build_table(fits, base_table=table, manifest=manifest, rows=len(rows)),
        subgate=measure_subgate(subgate_groups) if subgate_groups is not None else None,
    )


def calibrate_from_manifest(
    path: str | Path,
    *,
    contracts_dirs: Sequence[str | Path] | None = None,
    verifiers: Sequence[Any],
    base_table: ThresholdTable | None = None,
    subgate_groups: Iterable[Mapping[str, Any]] | None = None,
) -> CalibrationResult:
    """``calibrate`` over a manifest on disk, read through the loader ``core.gate`` owns.

    Takes a path. The holdout and its 50-100 labelled images are DATA and stay outside the wheel:
    nothing here ships a corpus, and nothing here writes one.
    """
    rows = load_manifest(path)
    roots = [Path(r) for r in (contracts_dirs or [])]
    return calibrate(
        rows,
        store=ContractStore(roots),
        verifiers=verifiers,
        base_table=base_table,
        manifest=str(path),
        subgate_groups=subgate_groups,
    )
