"""The asset record: per-asset provenance, persisted and replayable (PIN_PER_STEP).

This record is BOTH the audit trail and the training set for the offline optimizer — the same pinned
fields that make a run replayable (contract hash, compiled synth id, generator id+seed+sampler,
the prompt actually sent, the image it produced, verifier ids+versions, the per-atom gate
transcript, the question DAG) are the features GEPA learns from.

CORRECTED IN PLACE (F-f99c78f8). This docstring used to end "``replay`` recomputes the contract
hash and reconstructs the question DAG, asserting the gate is reproducible bit-for-bit." That is a
claim the function does not make. Reconstructing the DAG and matching hashes proves the QUESTIONS
reproduce; ``replay`` touches no score, no zone, no verifier version and no pixel. What it asserts
is stated on ``replay`` itself now, in the terms it actually checks."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...errors import PromptCraftError
from ..contract.compile_questions import QuestionDAG, compile_questions
from ..contract.hash import contract_hash
from ..contract.schema import ResolvedContract
from ..gate.checkpoint import ContrastiveCheckpoint
from ..gate.harness import GateTranscript
from ..gate.thresholds import ThresholdTable
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
    thresholds_fingerprint: str = ""
    """Content hash of the band VALUES the decision was made under (F-70ea9458).

    ``thresholds_version`` is a hand-maintained label and nothing binds it to the numbers, so a
    retune that forgets the version bump replays clean: MEASURED, moving vqa from {0.80, 0.40} to
    {0.20, 0.05} left both tables reporting 'sprite.cal.v1' and ``replay`` compared two identical
    strings and reported success, while a score of 0.50 had moved from UNCERTAIN to PASS.

    Additive, and absent means legacy: a receipt written before this field existed carries "" and
    is checked on the version alone -- the same back-compat rule ``schema_version`` established,
    for the same reason. STABILITY.md's promise is unchanged in both halves: retuning bands is
    still not a breaking change, and "a decision cannot be silently replayed under another table"
    is now mechanically true rather than a maintainer's discipline."""
    question_dag: QuestionDAG  # stored so the gate is replayable
    gate_transcript: GateTranscript
    retry_count: int
    decision: str  # "bound" | "escalated" | "blocked"
    attempts: list[Attempt] = Field(default_factory=list)
    checkpoint: ContrastiveCheckpoint | None = None
    # ------------------------------------------------------------------ F-f99c78f8
    # The receipt could not identify the artifact it certifies. All additive, all defaulted, so
    # every receipt already on disk keeps loading under schema_version "1".
    image_path: str = ""
    """The file the gate actually scored. A 'bound' receipt without it left an operator holding a
    directory of renders and no mechanical way to say which pixels were certified -- for a record
    whose module docstring opens "per-asset provenance"."""
    created_at: str = ""
    """UTC ISO-8601. The record had no time field at all, so nothing on disk could establish that
    a replacement had happened or which of two receipts was newer."""
    prompt: str = ""
    """The prompt actually sent to the generator. PIN_PER_STEP is "model + prompt + tool-schema
    pinned per step"; on the dspy backend the prompt is recoverable only from out-of-receipt state
    (the pinned artifact still existing, the predictor being deterministic), so it is stored."""
    negative_prompt: str = ""


def persist(record: AssetRecord, records_dir: str | Path) -> Path:
    """Write the receipt. A receipt already on disk is never replaced (F-a99ec99e).

    This used to be a plain truncating ``write_text`` to a path derived from a non-unique
    ``record_id``. MEASURED end to end: run 1 bound and wrote
    ``char_ashen-reaver-seed1000.json``; run 2, same records dir, same contract, one score
    changed, escalated and wrote the IDENTICAL path -- after which the directory held one file
    reading 'escalated' and the gate transcript that justified the bind was unrecoverable. The
    collision landed on precisely the runs that matter, because ``base_seed`` defaults to 1000 and
    best-of-N early-exits on the first clean PASS, so the common bound case always wrote seed1000.

    The system's own model already said this write was irreversible: ``compensators`` registers
    ``records-write`` with post_state "receipt deleted by id" and an owner, and ``run()`` requires
    it before both doors -- so the registry was consulted for permission to write, and the
    deletion it exists to compensate then happened unattended, with no owner and no notice.

    Two independent changes, both cheap. ``orchestrate._build_record`` widens ``record_id`` so
    ordinary re-binds accumulate rather than replace (the filename is not a covered surface;
    ``record_id`` inside the receipt is data, extended additively). This function closes the
    residual: the target is claimed with ``O_EXCL``, so a collision is an ANSWER
    (``IO_RECORD_EXISTS``) rather than a deletion, and it is claimed atomically rather than via an
    exists() check a second process could race. A crash mid-write can still leave a short file --
    but only at a path that provably held nothing, which is the property that matters here.
    """
    d = Path(records_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{record.record_id}.json"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as err:
        raise PromptCraftError(
            "IO_RECORD_EXISTS",
            f"a receipt already exists at {path}; prompt-craft does not overwrite a receipt "
            f"(record_id {record.record_id!r})",
            cause=err,
        ) from err
    except OSError as err:
        raise PromptCraftError(
            "IO_RECORD_WRITE", f"could not write record {path}: {err.strerror or err}", cause=err,
            hint="Check that the records dir is writable and has space.",
        ) from err
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(record.model_dump_json(indent=2))
    return path


def receipt_paths(records_dir: str | Path) -> list[Path]:
    """Every ``*.json`` receipt directly under ``records_dir``, in sorted order. A pure read.

    ONE walk, owned by the module that WRITES the files it walks. ``persist`` decides what a
    receipt is called and where it lands, so the answer to "which files in this directory are
    receipts" belongs beside it -- ``regrade_dir`` (F-dec37d4e) and the receipt index
    (F-b0e6dde7) both ask it, and two spellings of it would drift the first time either side
    was edited.

    Not recursive, and that is the load-bearing half. ``persist`` writes receipts FLAT into the
    records dir; the subdirectories that appear beside them hold generated images, and (since
    F-2b04f0b8) the ``dispositions/`` entries that resolve escalations. Neither is a receipt,
    and a recursive walk would hand both to ``load()`` and get a coded refusal for a file that
    was never claiming to be one.

    A records dir that does not exist yields ``[]`` rather than a refusal: this is the walk, not
    the policy. A caller for whom "that directory is not there" and "that directory is empty"
    are different answers -- the listing surface, where a typo must not read as "no receipts" --
    checks first and says so in its own terms.
    """
    d = Path(records_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def load(path: str | Path) -> AssetRecord:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as err:
        # F-5592ffad: both arms produced the byte-identical sentence "could not read record <p>",
        # so the message could not tell "you pointed at nothing" from "this file is damaged" --
        # two situations whose recoveries have nothing in common. One code, two messages.
        raise PromptCraftError(
            "IO_RECORD_READ", f"could not read record {p}: {err.strerror or err}", cause=err
        ) from err
    except json.JSONDecodeError as err:
        raise PromptCraftError(
            "IO_RECORD_READ", f"could not read record {p}: not valid JSON ({err})", cause=err
        ) from err
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
    record: AssetRecord,
    resolved: ResolvedContract,
    *,
    thresholds_version: str | None,
    thresholds: ThresholdTable | None = None,
) -> QuestionDAG:
    """Assert that this receipt still reproduces, and say exactly what that means.

    Three checks, and no more: the threshold table the decision was made under still matches (by
    version, and by band VALUES when a table is supplied); the contract still hashes to what was
    bound; and the question DAG still compiles to the stored one. It re-scores nothing, consults
    no verifier and never looks at the image -- ``replay`` proves the QUESTIONS reproduce, not
    that the pixels would be judged the same way today (F-f99c78f8: the module docstring used to
    claim "the gate is reproducible bit-for-bit", which is a stronger sentence than the code).
    Any divergence raises STATE_REPLAY_DRIFT.

    ``thresholds_version`` is keyword-only and has NO default on purpose. The record has always
    stamped the table version and nothing ever compared it, so a replay under a retuned table
    silently re-decided and reported success -- a check that looked live while doing less than it
    appeared to. Passing ``None`` is still allowed, but it is now an explicit statement that the
    caller does not have a table to compare against, rather than a default nobody noticed.

    ``thresholds`` (F-70ea9458) is the same statement made about the NUMBERS. A version string is
    hand-maintained and nothing binds it to the bands it names, so a retune that forgets the
    version bump passes the check above by comparing two identical strings. Pass the table you
    loaded and the band values are compared too. Optional and additive because a caller who has
    only the version string is exactly the caller the older, weaker check was written for."""
    if thresholds_version is None and thresholds is not None:
        thresholds_version = thresholds.version
    # --- F-154dd9b2. These four raise sites are ONE code and four different refusals, and all
    # four used to pass no inline hint, so every one resolved DEFAULT_HINTS['STATE_REPLAY_DRIFT']
    # -- whose LEAD remedy ("re-run replay with --thresholds pointed at the table the receipt
    # names") is IMPOSSIBLE for the value-drift arm and IRRELEVANT for the two contract arms,
    # which --thresholds cannot affect at all. The code stays one code: STABILITY.md says parse
    # the code, not the prose. The prose stops being written for the arm the operator is least
    # likely to hit, the way preflight.py already gives its three IO_GATE_INPUT sites three
    # different hints. DEFAULT_HINTS keeps the generic text as the fallback.
    #
    # (a) VERSION drift -- the one arm the generic hint was actually written for, so it keeps it.
    if thresholds_version is not None and thresholds_version != record.thresholds_version:
        raise PromptCraftError(
            "STATE_REPLAY_DRIFT",
            f"threshold drift for {record.record_id}: the receipt was decided under table "
            f"{record.thresholds_version!r}, this run loaded {thresholds_version!r}. The same "
            f"scores can land in a different zone under a different table.",
            hint=f"Two different tables. Re-run replay with --thresholds pointed at "
            f"{record.thresholds_version!r}, the table this receipt names, or accept the retune "
            f"and re-bind the asset under the table you loaded. Do not edit the receipt.",
        )
    if thresholds is not None and record.thresholds_fingerprint:
        # Absent fingerprint == a receipt written before the field existed; it keeps the older,
        # weaker promise rather than being refused. Present-and-different is an UNDECLARED retune:
        # the label says one table, the bands are a different one.
        live = thresholds.fingerprint()
        if live != record.thresholds_fingerprint:
            # (b) VALUE drift. The refusal's whole premise is that BOTH tables call themselves
            # the same version, so "point --thresholds at the table the receipt names" names the
            # very file that just failed, and following it re-runs the identical command for the
            # identical refusal. The two real recoveries appear nowhere in the generic text.
            raise PromptCraftError(
                "STATE_REPLAY_DRIFT",
                f"threshold VALUE drift for {record.record_id}: both this run and the receipt say "
                f"table {record.thresholds_version!r}, but the band values differ (receipt "
                f"{record.thresholds_fingerprint}, this run {live}). Retuning bands is not a "
                f"breaking change; retuning them without moving the version is a decision "
                f"replayed under a table that is not the one it names.",
                hint=f"Both tables call themselves {record.thresholds_version!r}, so --thresholds "
                f"cannot point at a different one. Either restore the band values this receipt "
                f"was decided under (its fingerprint is {record.thresholds_fingerprint}), or keep "
                f"the retune, bump the table's version, and re-bind the asset.",
            )
    live_hash = contract_hash(resolved)
    if live_hash != record.contract_hash:
        # (c) CONTRACT-HASH drift, the most reachable arm of the four -- contracts are edited
        # constantly and calibration tables almost never are. The whole message used to be
        # "contract hash drift for <record_id>: the contract changed since this asset was bound":
        # neither hash, no revision, not even the contract id, while the two threshold arms above
        # print both sides. It was then handed a hint whose first move is about --thresholds, a
        # flag that cannot affect this check at all.
        raise PromptCraftError(
            "STATE_REPLAY_DRIFT",
            f"contract hash drift for {record.record_id}: contract {record.contract_id!r} no "
            f"longer hashes to what was bound (receipt {record.contract_hash}, this run "
            f"{live_hash})",
            hint="Restore the contract revision that was bound, or accept the edit and re-bind "
            "the asset under it. --thresholds does not affect this check.",
        )
    rebuilt = compile_questions(resolved)
    if rebuilt.model_dump() != record.question_dag.model_dump():
        # (d) DAG drift is reached only when the contract hash MATCHED and compile_questions
        # still produced a different DAG, so the contract is not what changed -- the realistic
        # cause is a prompt-craft VERSION change, which the generic hint never mentions.
        raise PromptCraftError(
            "STATE_REPLAY_DRIFT",
            f"question DAG for {record.record_id} does not reproduce from contract "
            f"{record.contract_id!r} (the contract hash matched, so the contract did not change)",
            hint="The contract still hashes correctly, so this build compiles the same contract "
            "into a different question DAG. That is a prompt-craft version change: re-bind under "
            "this build, or read the receipt with the build that wrote it.",
        )
    return rebuilt
