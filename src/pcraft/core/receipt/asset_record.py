"""The asset record: per-asset provenance, persisted and replayable (PIN_PER_STEP).

This record is BOTH the audit trail and the training set for the offline optimizer — the same pinned
fields that make a run replayable (contract hash, compiled synth id, generator id+seed+sampler,
verifier ids+versions, the per-atom gate transcript, the question DAG) are the features GEPA learns
from. ``replay`` recomputes the contract hash and reconstructs the question DAG, asserting the gate
is reproducible bit-for-bit."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...errors import PromptCraftError
from ..contract.compile_questions import QuestionDAG, compile_questions
from ..contract.hash import contract_hash
from ..contract.schema import ResolvedContract
from ..gate.checkpoint import ContrastiveCheckpoint
from ..gate.harness import GateTranscript
from ..loop.retry_policy import Attempt

RECORD_SCHEMA_VERSION = "1"
"""The on-disk receipt format this build writes.

Receipts are read back by ``replay`` long after the run that wrote them, so the format is a
PUBLIC surface under semver -- see STABILITY.md. Before this field existed the reader was
fail-closed in BOTH directions (``extra="forbid"`` rejects an added field; a required field
rejects a dropped one), which meant any future change to the record invalidated every receipt
already on disk with no migration path and no way to tell "written by a newer prompt-craft"
from "corrupt". This version, and the branch in ``load()``, are what make that survivable."""

_SUPPORTED_RECORD_SCHEMAS = frozenset({"1"})


class AssetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = RECORD_SCHEMA_VERSION
    record_id: str
    contract_id: str
    contract_hash: str
    compiled_synth_id: str
    synth_backend: str
    synth_degraded: bool
    generator_id: str
    generator_family: str
    seed: int
    sampler: str
    conditioning: dict
    verifier_ids: list[str]  # "id@version" per gate tier used
    thresholds_version: str
    question_dag: QuestionDAG  # stored so the gate is replayable
    gate_transcript: GateTranscript
    retry_count: int
    decision: str  # "bound" | "escalated" | "blocked"
    attempts: list[Attempt] = Field(default_factory=list)
    checkpoint: ContrastiveCheckpoint | None = None


def persist(record: AssetRecord, records_dir: str | Path) -> Path:
    d = Path(records_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{record.record_id}.json"
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def load(path: str | Path) -> AssetRecord:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise PromptCraftError("IO_RECORD_READ", f"could not read record {p}", cause=err) from err
    if not isinstance(data, dict):
        raise PromptCraftError(
            "IO_RECORD_INVALID", f"record {p} is valid JSON but not an object"
        )
    # Absent means v1: receipts written before the field existed are still readable, which is
    # the entire point of adding it. Present-and-unknown is a DIFFERENT answer from invalid --
    # "written by a newer prompt-craft" is not "corrupt", and collapsing the two would send a
    # reader off debugging a file that is perfectly well formed.
    raw = data.get("schema_version")
    version = "1" if raw is None else str(raw)
    if version not in _SUPPORTED_RECORD_SCHEMAS:
        raise PromptCraftError(
            "IO_RECORD_SCHEMA_UNSUPPORTED",
            f"record {p} declares schema_version {version!r}; this build reads "
            f"{sorted(_SUPPORTED_RECORD_SCHEMAS)}",
        )
    return _READERS[version](data, p)


def _read_v1(data: dict, p: Path) -> AssetRecord:
    try:
        return AssetRecord.model_validate(data)
    except ValidationError as err:
        raise PromptCraftError(
            "IO_RECORD_INVALID",
            f"record {p} failed schema validation",
            cause=err,
        ) from err


_READERS = {"1": _read_v1}


def replay(
    record: AssetRecord, resolved: ResolvedContract, *, thresholds_version: str | None
) -> QuestionDAG:
    """Reconstruct the question DAG from the resolved contract and assert it matches the stored one,
    the stored contract hash, and the threshold table that made the decision. Raises
    STATE_REPLAY_DRIFT on any divergence.

    ``thresholds_version`` is keyword-only and has NO default on purpose. The record has always
    stamped the table version and nothing ever compared it, so a replay under a retuned table
    silently re-decided and reported success -- a check that looked live while doing less than it
    appeared to. Passing ``None`` is still allowed, but it is now an explicit statement that the
    caller does not have a table to compare against, rather than a default nobody noticed."""
    if thresholds_version is not None and thresholds_version != record.thresholds_version:
        raise PromptCraftError(
            "STATE_REPLAY_DRIFT",
            f"threshold drift for {record.record_id}: the receipt was decided under table "
            f"{record.thresholds_version!r}, this run loaded {thresholds_version!r}. The same "
            f"scores can land in a different zone under a different table.",
        )
    if contract_hash(resolved) != record.contract_hash:
        raise PromptCraftError(
            "STATE_REPLAY_DRIFT",
            f"contract hash drift for {record.record_id}: the contract changed since this asset was bound",
        )
    rebuilt = compile_questions(resolved)
    if rebuilt.model_dump() != record.question_dag.model_dump():
        raise PromptCraftError(
            "STATE_REPLAY_DRIFT",
            f"question DAG for {record.record_id} does not reproduce from the contract",
        )
    return rebuilt
