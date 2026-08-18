"""The asset record: per-asset provenance, persisted and replayable (PIN_PER_STEP).

This record is BOTH the audit trail and the training set for the offline optimizer — the same pinned
fields that make a run replayable (contract hash, compiled synth id, generator id+seed+sampler,
verifier ids+versions, the per-atom gate transcript, the question DAG) are the features GEPA learns
from. ``replay`` recomputes the contract hash and reconstructs the question DAG, asserting the gate
is reproducible bit-for-bit."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from ...errors import PromptCraftError
from ..contract.compile_questions import QuestionDAG, compile_questions
from ..contract.hash import contract_hash
from ..contract.schema import ResolvedContract
from ..gate.harness import GateTranscript


class AssetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    try:
        return AssetRecord.model_validate(data)
    except ValidationError as err:
        raise PromptCraftError(
            "IO_RECORD_INVALID",
            f"record {p} failed schema validation",
            cause=err,
        ) from err


def replay(record: AssetRecord, resolved: ResolvedContract) -> QuestionDAG:
    """Reconstruct the question DAG from the resolved contract and assert it matches the stored one
    and the stored contract hash. Raises STATE_REPLAY_DRIFT on any divergence."""
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
