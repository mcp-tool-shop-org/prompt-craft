"""What the human decided at an escalation checkpoint, recorded beside the receipt.

F-2b04f0b8. The loop builds a genuine contrastive checkpoint (``build_checkpoint`` ->
``ContrastiveCheckpoint`` with per-atom claim/thought/chose plus the band margin), persists it
inside the receipt, prints it, and returns ``decision='escalated'``. Then the trail stopped:
there was no verb and no format for what the Director decided. The product's own model named the
missing half -- the ``escalation-ticket`` compensator declares owner "pipeline (Director
resolves)" and post-rollback state "ticket closed with a resolution note", and there was no
ticket, no resolution note, and no place to put one. At volume that made the Director's judgment
the one input to the pipeline that never became provenance: the same asset re-binds from
scratch, the same UNCERTAIN atom is re-escalated, and nothing on disk records that a human
already looked at it and said yes.

THE DESIGN CHOICE, AND WHY IT IS A SIBLING FILE
-----------------------------------------------
Three shapes were available: a new field on ``AssetRecord``, a re-write of the receipt, or a
separate record. It is a separate record, and each of the other two is refused by something the
product already promises.

Not a re-write. ``persist``'s O_EXCL rule (F-a99ec99e) is that a receipt already on disk is never
replaced, ``STABILITY.md`` promises a ``schema_version: "1"`` receipt keeps loading, and
``STATE_REPLAY_DRIFT``'s own hint ends "Do not edit the receipt". A resolution that mutated the
file would break all three at once, and would make the audit trail a document that gets updated
when someone changes their mind -- the exact property ``regrade``'s READ-ONLY section exists to
protect.

Not a field on ``AssetRecord`` either, even an additive defaulted one. The receipt is written
ONCE, at the moment of the decision, by a process that has already exited by the time a human
looks at the checkpoint; a field that can only ever be filled in later is a field that is
structurally empty in every receipt this product writes. Adding it would also put a mutable fact
inside the immutable record and immediately re-raise the re-write question.

So: a sibling, in a ``dispositions/`` SUBDIRECTORY of the records dir. The subdirectory is
load-bearing rather than tidy. ``receipt_paths`` walks ``*.json`` NON-recursively, so every
existing reader -- ``regrade_dir``, the index, any caller globbing the records dir -- sees
exactly what it saw before, and a disposition can never collide with the path ``persist`` claims
with O_EXCL or be handed to ``load()`` as a malformed receipt. Old readers and ``replay`` are
untouched by construction: they read a file this module never writes to.

WHAT IT IS NOT
--------------
It is not a way to auto-accept. UNCERTAINTY_GATED_HUMANS makes the checkpoint the artifact a
human reads, and this is the answer to it, not a bypass of it: nothing in ``orchestrate`` reads a
disposition, no gate consults one, and ``OrchestrationResult.decision`` keeps its two-value
Literal (F-a250372c) rather than growing a third value that every caller would have to learn.
The covered exit-code contract is untouched for the same reason -- "a human accepted this" must
never become exit 0 from ``bind``, because that would make the gate's refusal retroactively
invisible to a scripted caller. ``bind`` still exits 3 or 4; the acceptance is a separate,
later, attributed act.

And it refuses to be an unattributed one: a disposition needs a named human and a receipt that
actually escalated, or it is not evidence that anybody decided anything.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError

from ...errors import PromptCraftError
from ..loop.compensators import CompensatorRegistry, default_registry
from .asset_record import AssetRecord

DISPOSITION_SCHEMA_VERSION = "1"
"""The on-disk resolution format this build writes.

A second on-disk format gets the same reader contract as the first: a version marker, a
supported set, and a distinct answer for present-and-newer. ``schema_version`` earned that on
the receipt by NOT having it -- the reader was fail-closed in both directions and any future
change would have invalidated every file already written."""

_SUPPORTED_DISPOSITION_SCHEMAS = frozenset({"1"})

DISPOSITIONS_DIRNAME: Final[str] = "dispositions"
"""The subdirectory of the records dir that holds resolution entries.

Named here rather than spelled at each site because it is an on-disk convention two modules
depend on (this one writes it, ``receipt.index`` reads it) and the whole safety argument above
rests on it being a SUBdirectory of the records dir rather than a sibling suffix inside it."""

RESOLUTIONS: Final[tuple[str, ...]] = ("accepted", "rejected", "deferred")
"""The three answers a human can give a checkpoint.

``accepted`` -- I looked, and this asset is good enough to use despite the gate's refusal.
``rejected`` -- I looked, and it is not; do not re-roll this one hoping for a different score.
``deferred`` -- I looked and I am not deciding yet, which is a different fact from not having
looked, and is the one that stops an asset being silently re-escalated forever.

A closed set, checked at the door, because the value is what a downstream reader filters on: an
open string field would make "accepted" and "approved" and "ok" three unrelated answers to one
question."""

DISPOSITION_ACTION: Final[str] = "disposition-write"
"""The NAMED_COMPENSATORS action this write is registered under (no skip).

Writing a resolution is irreversible in the sense that matters here: it becomes part of the
audit trail, and something downstream may act on "a human accepted this". Every other
irreversible action in this loop states its undo and its owner before it happens, and there is
no argument for this one being the exception -- least of all when the finding's own must-not-
break list names the requirement."""


class Disposition(BaseModel):
    """One human decision about one escalated receipt.

    Every field is either the human's answer or a fact copied from the receipt at the moment of
    the decision. The copies are not redundancy: they are what lets the index answer "which
    escalations has a human resolved, under which contract revision" without loading and
    re-validating every receipt in the directory, and they are what makes a disposition
    self-describing if it is ever read on its own.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: str = DISPOSITION_SCHEMA_VERSION
    record_id: str
    """The receipt this resolves, by its CONTENT id. Never a filename: ``_record_id`` pushes
    everything through ``_fs_safe`` and the receipt filename is not a covered surface."""
    contract_id: str = ""
    resolution: str
    resolved_by: str
    """Who decided. Free text, because the identity system is the deployment's, not ours -- but
    non-empty, checked at the door."""
    resolved_at: str = ""
    """UTC ISO-8601, supplied by the caller. See ``record_disposition`` for why it is injectable."""
    note: str = ""
    """The resolution note the ``escalation-ticket`` compensator has always promised and never
    had anywhere to live."""
    contract_hash: str = ""
    thresholds_fingerprint: str = ""
    """Copied from the receipt, so a decision can be told apart from a decision made under a
    contract revision or a calibration that has since moved. The same reason ``replay`` compares
    both: an acceptance is only meaningful relative to what was being accepted."""
    checkpoint_digest: str = ""
    """A content hash of the checkpoint text the human was shown, or "" when the receipt carried
    no checkpoint. "I accepted this" is provenance only if the record says what "this" was; the
    digest is what stops a resolution being silently re-read as an answer to a different
    escalation."""


def checkpoint_digest(record: AssetRecord) -> str:
    """Hash the checkpoint text this receipt carries. ``""`` when it carries none.

    The TEXT, not the model dump: the text is the artifact the human actually read (it is what
    ``OrchestrationResult.reason`` carries and what the CLI prints), and hashing the structure
    instead would make the digest move when a rendering change left the words identical.
    """
    if record.checkpoint is None:
        return ""
    return "sha256:" + hashlib.sha256(record.checkpoint.text.encode("utf-8")).hexdigest()[:16]


def dispositions_dir(records_dir: str | Path) -> Path:
    """Where resolution entries live for this records dir. Does not create it."""
    return Path(records_dir) / DISPOSITIONS_DIRNAME


def record_disposition(
    record: AssetRecord,
    records_dir: str | Path,
    *,
    resolution: str,
    resolved_by: str,
    note: str = "",
    resolved_at: str = "",
    compensators: CompensatorRegistry | None = None,
) -> Path:
    """Write the human's decision beside ``record``. The receipt itself is never touched.

    ``resolved_at`` is injectable and defaults to "stamp it now". PIN_PER_STEP is the reason it
    can be injected at all: a trail whose stamps come from a wall clock cannot be replayed or
    asserted, so the tests that prove this feature pass their own time rather than measuring the
    machine's. It is also what makes the FILENAME deterministic, which matters below.

    Entries ACCUMULATE. The path carries the stamp, so a human who looks twice leaves two
    entries and neither write can destroy the other -- the same widening ``_record_id`` needed
    (F-a99ec99e) after two runs of one contract targeted one path and the second truncated the
    first. The exact path is still claimed with O_EXCL, so a genuine collision is an ANSWER
    (``IO_DISPOSITION_EXISTS``) rather than a deletion.

    Three refusals before anything is written, all of them about what this record is FOR:
    a receipt that did not escalate has nothing for a human to resolve; a resolution with no
    human named on it is not evidence a human decided; and a resolution outside ``RESOLUTIONS``
    is a verdict nothing downstream can read.

    The compensator check is last of the four and still BEFORE the write, exactly as
    ``orchestrate.run`` requires ``records-write`` before both of its doors.
    """
    if record.decision != "escalated":
        raise PromptCraftError(
            "INPUT_DISPOSITION_TARGET",
            f"receipt {record.record_id!r} decided {record.decision!r}, so there is no "
            f"escalation for a human to resolve",
        )
    if not resolved_by.strip():
        raise PromptCraftError(
            "INPUT_DISPOSITION_ACTOR",
            f"no human is named on this resolution of receipt {record.record_id!r}",
        )
    if resolution not in RESOLUTIONS:
        raise PromptCraftError(
            "INPUT_DISPOSITION_RESOLUTION",
            f"resolution {resolution!r} is not one of {', '.join(RESOLUTIONS)}",
        )

    stamp = resolved_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    entry = Disposition(
        record_id=record.record_id,
        contract_id=record.contract_id,
        resolution=resolution,
        resolved_by=resolved_by.strip(),
        resolved_at=stamp,
        note=note,
        contract_hash=record.contract_hash,
        thresholds_fingerprint=record.thresholds_fingerprint,
        checkpoint_digest=checkpoint_digest(record),
    )

    (compensators or default_registry()).require(DISPOSITION_ACTION)

    d = dispositions_dir(records_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_fs_safe(record.record_id)}-{_fs_safe(stamp)}.json"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as err:
        raise PromptCraftError(
            "IO_DISPOSITION_EXISTS",
            f"a resolution already exists at {path}; prompt-craft does not overwrite one "
            f"(record_id {record.record_id!r}, resolved_at {stamp!r})",
            cause=err,
        ) from err
    except OSError as err:
        raise PromptCraftError(
            "IO_DISPOSITION_WRITE",
            f"could not write resolution {path}: {err.strerror or err}",
            cause=err,
        ) from err
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(entry.model_dump_json(indent=2))
    return path


def _fs_safe(text: str) -> str:
    """Reduce to characters that are a filename on every platform this ships to.

    The same sanitizer ``orchestrate._record_id`` needs, for the same measured reason: on NTFS a
    colon in a path is not an error, it opens an ALTERNATE DATA STREAM -- the file writes,
    ``exists()`` returns True, and the directory listing is empty. ``resolved_at`` is an ISO-8601
    stamp, which is nothing but colons.
    """
    return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in text)


def load_disposition(path: str | Path) -> Disposition:
    """Read one resolution entry. Same reader contract as ``asset_record.load``.

    Three distinct answers, because they have three distinct recoveries: unreadable-or-not-JSON,
    well-formed-but-not-this-schema, and well-formed-and-NEWER. The third is not corruption and
    must not send a reader off deleting a good file and re-deciding.
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as err:
        raise PromptCraftError(
            "IO_DISPOSITION_READ", f"could not read resolution {p}: {err.strerror or err}",
            cause=err,
        ) from err
    except json.JSONDecodeError as err:
        raise PromptCraftError(
            "IO_DISPOSITION_READ", f"could not read resolution {p}: not valid JSON ({err})",
            cause=err,
        ) from err
    if not isinstance(data, dict):
        raise PromptCraftError(
            "IO_DISPOSITION_INVALID", f"resolution {p} is valid JSON but not an object"
        )
    raw = data.get("schema_version")
    version = "1" if raw is None else str(raw)
    if version not in _SUPPORTED_DISPOSITION_SCHEMAS:
        raise PromptCraftError(
            "IO_DISPOSITION_SCHEMA_UNSUPPORTED",
            f"resolution {p} declares schema_version {version!r}; this build reads "
            f"{sorted(_SUPPORTED_DISPOSITION_SCHEMAS)}",
        )
    try:
        return Disposition.model_validate(data)
    except ValidationError as err:
        raise PromptCraftError(
            "IO_DISPOSITION_INVALID", f"resolution {p} failed schema validation", cause=err
        ) from err


def disposition_paths(records_dir: str | Path) -> list[Path]:
    """Every resolution entry under ``<records_dir>/dispositions``, sorted. Pure read.

    Absent directory yields ``[]``: a records dir in which nothing has ever been resolved is the
    normal case, not a refusal.
    """
    d = dispositions_dir(records_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def dispositions_for(records_dir: str | Path, record_id: str) -> list[Disposition]:
    """Every resolution recorded against ``record_id``, oldest first.

    Ordered by ``resolved_at`` -- the fact, not the filename -- so the ordering survives the
    sanitizer and does not depend on a path convention this module could change. A file that
    cannot be read is a REFUSAL here, unlike in the index: a caller who names one receipt is
    asking a question about that receipt, and answering it from a partial set would be a wrong
    answer rather than an incomplete listing.
    """
    entries = [load_disposition(p) for p in disposition_paths(records_dir)]
    return sorted(
        (d for d in entries if d.record_id == record_id), key=lambda d: d.resolved_at
    )


__all__ = [
    "DISPOSITIONS_DIRNAME",
    "DISPOSITION_ACTION",
    "DISPOSITION_SCHEMA_VERSION",
    "RESOLUTIONS",
    "Disposition",
    "checkpoint_digest",
    "disposition_paths",
    "dispositions_dir",
    "dispositions_for",
    "load_disposition",
    "record_disposition",
]
