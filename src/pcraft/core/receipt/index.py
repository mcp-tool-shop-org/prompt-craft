"""Read a records directory in aggregate: list, filter, summarize. Never write.

F-b0e6dde7. The provenance data existed and nothing read it in aggregate: ``persist()`` writes
one file, ``load()`` reads one path, ``replay()`` checks one record, and the only directory walk
in the whole package was the contract loader's. There was no listing, no index, no filter, no
rollup -- and the gap was named by the product's own model, since the ``records-write``
compensator declares its post-rollback state as "receipt deleted by id; provenance index
re-indexed", an index prompt-craft did not have.

At volume the questions with no mechanical answer were: which assets are bound and which
escalated; which contract revision each was bound under; which threshold table and fingerprint;
which receipts are stale against today's contract; which escalated and on which atoms. Every one
of those fields is already on ``AssetRecord``. The only approach was a shell loop over ``pcraft
replay``, which is all-or-nothing: the first drifted receipt exits 2 and the loop tells you
nothing about the rest.

Four properties, each one a promise this module would be easy to break.

IT IS A DERIVED READ. Nothing here writes, and in particular nothing is written back into the
records dir, where it could collide with the path ``persist`` claims with O_EXCL or be mistaken
for a receipt by the next reader. The index is rebuilt from the files each time it is asked for;
that is cheap, and it is the only version that cannot go stale.

IT IS KEYED ON CONTENTS. ``record_id`` comes from inside the file, never from the filename. The
receipt filename is not a covered surface -- ``orchestrate._record_id`` pushes everything through
``_fs_safe``, whose docstring records an NTFS alternate-data-stream near-miss -- so a row whose
identity came from ``path.stem`` would be an index built on the one string this product reserves
the right to change. A file that cannot be read therefore carries NO id, rather than a guess.

THE FIRST BAD FILE DOES NOT END THE REPORT. An unreadable or newer-schema receipt is reported as
a ROW carrying its own code, and the scan continues. That is the exact failure the shell-loop
workaround has, and reproducing it here would leave the feature no better than the thing it
replaces. It is also the deliberate difference from ``regrade_dir``, which still refuses: a
re-grade computes a number over a corpus and a missing member corrupts it, while a listing's
whole job is to say what is in the directory, including the parts that do not load.

A LISTING THAT FOUND PROBLEMS IS NOT A GATE THAT FAILED. ``scan`` returns data. It raises for
exactly one thing -- a records dir that is not there -- because "you pointed at nothing" must not
render as "you have no receipts". Everything else is a row, and the caller decides what it means.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ...errors import PromptCraftError
from ..gate.thresholds import Zone
from .asset_record import AssetRecord, load, receipt_paths
from .disposition import Disposition, disposition_paths, load_disposition


class RecordRow(BaseModel):
    """One FILE in the records dir, readable or not.

    Every field is copied from the receipt's contents; none is derived from the filename. The
    empty-string default is the same absent-is-empty convention the receipt itself uses for
    ``thresholds_fingerprint`` and ``image_path``, so a JSON consumer of this index never meets
    a null -- including for the rows where the file could not be read and nothing is known.
    """

    model_config = ConfigDict(extra="forbid")
    path: str
    """The file this row came from. For the operator to open; never parsed for identity."""
    record_id: str = ""
    contract_id: str = ""
    contract_hash: str = ""
    decision: str = ""
    created_at: str = ""
    image_path: str = ""
    thresholds_version: str = ""
    thresholds_fingerprint: str = ""
    retry_count: int = 0
    overall: str = ""
    """The gate roll-up the receipt stored. Quoted, not recomputed: it is what was decided."""
    flagged: list[str] = Field(default_factory=list)
    """Required atoms that failed or went unconfirmed -- "which escalated, and on which atoms".
    Read off the stored transcript through the transcript's own accessors, so this list means
    exactly what the gate meant by it."""
    code: str = ""
    """``""`` when the receipt loaded. Otherwise the coded refusal this file produced."""
    message: str = ""
    dispositions: list[Disposition] = Field(default_factory=list)
    """What a human decided about this escalation, oldest first (F-2b04f0b8). Joined on
    ``record_id`` from the sibling ``dispositions/`` directory."""

    @property
    def readable(self) -> bool:
        return not self.code

    @property
    def latest_resolution(self) -> str:
        """The most recent human answer, or ``""`` if nobody has answered.

        A property rather than a stored field: it is derived from ``dispositions`` and storing it
        would create a second place for the same fact to be wrong.
        """
        return self.dispositions[-1].resolution if self.dispositions else ""


class RecordQuery(BaseModel):
    """A filter over rows. Every field is optional and an unset field constrains nothing.

    All of these name a field that EXISTS on a receipt -- there is no filter here that the data
    cannot answer honestly. ``since`` / ``until`` compare ``created_at`` as strings, which is
    exactly right for ISO-8601 UTC stamps and deliberately avoids inventing date parsing and
    timezone arithmetic that the stored format does not need.

    A row that could not be read carries none of these fields, so it matches only ``unreadable``.
    That is why ``RecordIndex.summary()`` reports the directory rather than the filter: a filter
    must never be able to hide the fact that files here did not load.
    """

    model_config = ConfigDict(extra="forbid")
    contract: str = ""
    decision: str = ""
    resolution: str = ""
    """The LATEST human answer on this receipt (accepted / rejected / deferred)."""
    thresholds_version: str = ""
    since: str = ""
    until: str = ""
    unreadable: bool = False
    """Only the rows this build could not read."""
    stale_against: dict[str, str] = Field(default_factory=dict)
    """``contract_id -> the hash that contract has TODAY``. A row matches when its contract is a
    key here and its stored ``contract_hash`` differs.

    Supplied by the caller rather than resolved here on purpose: this module reads a directory,
    and quietly loading and hashing contracts behind the operator's back would make a pure read
    depend on a contract store, a search path, and a build's own compile step. "Stale" is a
    comparison, and the caller owns the thing being compared against.
    """

    def matches(self, row: RecordRow) -> bool:
        if self.unreadable != (not row.readable):
            return False
        exact = (
            (self.contract, row.contract_id),
            (self.decision, row.decision),
            (self.resolution, row.latest_resolution),
            (self.thresholds_version, row.thresholds_version),
        )
        if any(wanted and wanted != actual for wanted, actual in exact):
            return False
        if self.since and row.created_at < self.since:
            return False
        if self.until and row.created_at > self.until:
            return False
        if self.stale_against:
            # A contract this caller said nothing about cannot be called stale, so an unknown
            # contract_id is excluded rather than assumed drifted.
            live = self.stale_against.get(row.contract_id)
            return live is not None and live != row.contract_hash
        return True


class IndexSummary(BaseModel):
    """The rollup, over the whole directory. Never over a filtered subset."""

    model_config = ConfigDict(extra="forbid")
    records_dir: str
    total: int = 0
    readable: int = 0
    unreadable: int = 0
    by_decision: dict[str, int] = Field(default_factory=dict)
    by_contract: dict[str, int] = Field(default_factory=dict)
    by_thresholds_version: dict[str, int] = Field(default_factory=dict)
    by_resolution: dict[str, int] = Field(default_factory=dict)
    codes: dict[str, int] = Field(default_factory=dict)
    """Unreadable rows, counted by their refusal code. Always present, always the directory's."""
    earliest: str = ""
    latest: str = ""
    stray_dispositions: int = 0


class RecordIndex(BaseModel):
    """Everything one records directory holds, as data.

    ``rows`` is in the same sorted order ``receipt_paths`` walks, which is the order every other
    reader of this directory already uses.
    """

    model_config = ConfigDict(extra="forbid")
    records_dir: str
    rows: list[RecordRow] = Field(default_factory=list)
    stray_dispositions: list[str] = Field(default_factory=list)
    """Resolution entries that could not be read, or that name a receipt this directory does not
    hold. Reported rather than dropped: a decision file sitting beside receipts and attached to
    nothing is a fact the operator has to be told, and silently discarding it would be the same
    quiet incompleteness this module exists to remove."""

    def readable(self) -> list[RecordRow]:
        return [r for r in self.rows if r.readable]

    def unreadable(self) -> list[RecordRow]:
        return [r for r in self.rows if not r.readable]

    def query(self, q: RecordQuery | None = None) -> list[RecordRow]:
        return list(self.rows) if q is None else [r for r in self.rows if q.matches(r)]

    def summary(self) -> IndexSummary:
        """Counts over the DIRECTORY. See ``RecordQuery`` for why this never takes a filter."""
        out = IndexSummary(
            records_dir=self.records_dir,
            total=len(self.rows),
            readable=len(self.readable()),
            unreadable=len(self.unreadable()),
            stray_dispositions=len(self.stray_dispositions),
        )
        stamps = []
        for row in self.rows:
            if row.readable:
                _bump(out.by_decision, row.decision)
                _bump(out.by_contract, row.contract_id)
                _bump(out.by_thresholds_version, row.thresholds_version)
                if row.latest_resolution:
                    _bump(out.by_resolution, row.latest_resolution)
                if row.created_at:
                    stamps.append(row.created_at)
            else:
                _bump(out.codes, row.code)
        if stamps:
            out.earliest, out.latest = min(stamps), max(stamps)
        return out


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def scan(records_dir: str | Path) -> RecordIndex:
    """Read every receipt under ``records_dir`` and every resolution beside it. Writes nothing.

    Refuses exactly one thing: a records dir that is not a directory. A typo'd path answering
    "0 receipts" is the failure mode a listing surface most has to avoid, and it is the one an
    empty glob produces for free. A directory that exists and holds nothing is an empty index.
    """
    d = Path(records_dir)
    if not d.is_dir():
        raise PromptCraftError(
            "INPUT_RECORDS_DIR",
            f"records dir {d} does not exist or is not a directory, so there is nothing to list",
        )
    rows = [_row(p) for p in receipt_paths(d)]
    by_id: dict[str, RecordRow] = {r.record_id: r for r in rows if r.record_id}
    stray: list[str] = []
    for path in disposition_paths(d):
        try:
            entry = load_disposition(path)
        except PromptCraftError:
            stray.append(str(path))
            continue
        row = by_id.get(entry.record_id)
        if row is None:
            stray.append(str(path))
            continue
        row.dispositions.append(entry)
    for row in rows:
        row.dispositions.sort(key=lambda entry: entry.resolved_at)
    return RecordIndex(records_dir=str(d), rows=rows, stray_dispositions=stray)


def _row(path: Path) -> RecordRow:
    """One receipt, or the coded reason it is not one. Never raises."""
    try:
        record = load(path)
    except PromptCraftError as err:
        return RecordRow(path=str(path), code=err.code, message=err.message)
    return _row_from(path, record)


def _row_from(path: Path, record: AssetRecord) -> RecordRow:
    transcript = record.gate_transcript
    return RecordRow(
        path=str(path),
        record_id=record.record_id,
        contract_id=record.contract_id,
        contract_hash=record.contract_hash,
        decision=record.decision,
        created_at=record.created_at,
        image_path=record.image_path,
        thresholds_version=record.thresholds_version,
        thresholds_fingerprint=record.thresholds_fingerprint,
        retry_count=record.retry_count,
        overall=_zone_value(transcript.overall),
        flagged=[
            v.atom_id
            for v in (*transcript.failed_required(), *transcript.uncertain_required())
        ],
    )


def _zone_value(zone: Zone | str) -> str:
    return zone.value if isinstance(zone, Zone) else str(zone)


def stale_against(index: RecordIndex, live_hashes: Mapping[str, str]) -> list[RecordRow]:
    """Rows bound under a contract revision that is no longer what that contract hashes to.

    A convenience over ``RecordQuery(stale_against=...)`` for the caller who already holds the
    live hashes and wants the one answer, not a filter object.
    """
    return index.query(RecordQuery(stale_against=dict(live_hashes)))


__all__ = [
    "IndexSummary",
    "RecordIndex",
    "RecordQuery",
    "RecordRow",
    "scan",
    "stale_against",
]
