"""The v1.0.0 stability surface: the three checks that had to become real before semver
could mean anything here.

All three were the same defect wearing different clothes — a marker that reads as a
compatibility check and is never compared:

  * the receipt had no version at all, and its reader was fail-closed in BOTH directions,
    so any future record change invalidated every receipt already on disk;
  * the contract carried a ``$schema`` label that accepted literally any string;
  * the receipt stamped ``thresholds_version`` and nothing ever asserted it, so a replay
    under a retuned table silently re-decided and reported success.

Each test below pins one of those, in both directions where the criterion asked for both.
"""

from __future__ import annotations

import json

import pytest

from pcraft.core.contract.schema import CONTRACT_SCHEMA_ID, SUPPORTED_CONTRACT_SCHEMAS
from pcraft.core.receipt.asset_record import (
    RECORD_SCHEMA_VERSION,
    load,
    replay,
)
from pcraft.errors import PromptCraftError, exit_code_for
from pcraft.sample import load_sprite_example, run_mock_loop

# --------------------------------------------------------------------------------------
# 1. the receipt format is versioned, and the reader branches on it
# --------------------------------------------------------------------------------------


def test_a_receipt_written_before_the_field_existed_still_loads(tmp_path):
    """Absent means v1. This is the whole point of adding the field: the receipts already on
    disk when versioning landed must keep working, or the migration path we just built is the
    thing that breaks them."""
    res = run_mock_loop(records_dir=str(tmp_path))
    path = tmp_path / f"{res.record.record_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["schema_version"]  # exactly what a pre-1.0.0 receipt looks like
    path.write_text(json.dumps(data), encoding="utf-8")

    rec = load(path)
    assert rec.record_id == res.record.record_id
    assert rec.schema_version == RECORD_SCHEMA_VERSION


def test_a_receipt_from_the_future_is_refused_by_a_named_code_not_as_corruption(tmp_path):
    """"Written by a newer prompt-craft" and "corrupt" are different answers and must not
    collapse onto one code — the first is a well-formed file and re-binding it would destroy
    a perfectly good receipt."""
    res = run_mock_loop(records_dir=str(tmp_path))
    path = tmp_path / f"{res.record.record_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = "99"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PromptCraftError) as excinfo:
        load(path)
    assert excinfo.value.code == "IO_RECORD_SCHEMA_UNSUPPORTED"
    assert excinfo.value.code != "IO_RECORD_INVALID", "a future receipt is not a corrupt one"
    assert "99" in str(excinfo.value)


def test_a_genuinely_malformed_receipt_still_reports_as_invalid(tmp_path):
    """The other side of the same fence: adding the version branch must not turn real
    corruption into a version complaint."""
    path = tmp_path / "broken.json"
    path.write_text('{"schema_version": "1", "record_id": "only-one-field"}', encoding="utf-8")
    with pytest.raises(PromptCraftError) as excinfo:
        load(path)
    assert excinfo.value.code == "IO_RECORD_INVALID"


# --------------------------------------------------------------------------------------
# 2. the contract $schema label is load-bearing
# --------------------------------------------------------------------------------------


def test_a_contract_declaring_an_unsupported_schema_is_refused(tmp_path):
    """It accepted ``prompt-craft/contract.v99-NONSENSE`` without complaint until v1.0.0."""
    from pcraft.sample import load_store

    # A minimal contract on disk carrying a bogus $schema.
    contract = {
        "$schema": "prompt-craft/contract.v99-NONSENSE",
        "id": "example.bogus",
        "level": "faction",
        "must_have": [],
        "must_not": [],
    }
    d = tmp_path / "contracts"
    d.mkdir()
    (d / "example.bogus.contract.json").write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(PromptCraftError) as excinfo:
        load_store([d])
    assert excinfo.value.code == "CONTRACT_SCHEMA_UNSUPPORTED"
    assert exit_code_for(excinfo.value.code) == 1, "a bad contract is user input, exit 1"


def test_the_supported_schema_id_loads_and_the_shipped_contracts_use_it():
    """The refusal is only worth anything if the accepted value is the one actually shipped."""
    assert CONTRACT_SCHEMA_ID in SUPPORTED_CONTRACT_SCHEMAS
    store, _r, _t, _c = load_sprite_example()
    assert store.ids(), "the shipped example store must load under the enforced $schema"


# --------------------------------------------------------------------------------------
# 3. replay asserts the threshold table that made the decision
# --------------------------------------------------------------------------------------


def test_replay_under_a_different_threshold_table_raises_drift(tmp_path):
    """The scores in a receipt are only a decision relative to a table. Replaying under a
    different one and reporting OK is re-deciding in silence."""
    res = run_mock_loop(records_dir=str(tmp_path))
    store, _r, _t, _c = load_sprite_example()
    resolved = store.resolve(res.record.contract_id)

    with pytest.raises(PromptCraftError) as excinfo:
        replay(res.record, resolved, thresholds_version="some.other.table.v9")
    assert excinfo.value.code == "STATE_REPLAY_DRIFT"
    assert res.record.thresholds_version in str(excinfo.value)
    assert "some.other.table.v9" in str(excinfo.value)


def test_replay_under_the_recorded_table_passes(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    store, _r, _t, _c = load_sprite_example()
    resolved = store.resolve(res.record.contract_id)
    dag = replay(res.record, resolved, thresholds_version=res.record.thresholds_version)
    assert dag.contract_id == res.record.contract_id


def test_opting_out_of_the_threshold_check_is_explicit_not_a_default():
    """``thresholds_version`` is keyword-only with NO default. Passing ``None`` still skips the
    comparison, but a caller has to say so — which is the difference between a decision and an
    oversight. Asserted against the signature so a later default cannot reintroduce the silence.
    """
    import inspect

    sig = inspect.signature(replay)
    param = sig.parameters["thresholds_version"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty, (
        "a default here would restore the exact silence this check was added to remove"
    )
