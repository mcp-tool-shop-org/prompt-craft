from __future__ import annotations

import pytest

from pcraft.core.receipt.asset_record import load, replay
from pcraft.errors import PromptCraftError
from pcraft.sample import load_sprite_example, run_mock_loop


def test_receipt_round_trips_and_replays(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    assert res.record is not None
    path = tmp_path / f"{res.record.record_id}.json"
    assert path.exists()

    rec = load(path)
    store, _r, _t, _c = load_sprite_example()
    resolved = store.resolve(rec.contract_id)
    dag = replay(rec, resolved)  # no raise == the gate reproduces bit-for-bit
    assert dag.contract_id == rec.contract_id


def test_replay_detects_contract_drift(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    store, _r, _t, _c = load_sprite_example()
    resolved = store.resolve(res.record.contract_id)
    resolved.must_have[0].claim = "TAMPERED — the contract changed since bind"
    with pytest.raises(PromptCraftError) as exc:
        replay(res.record, resolved)
    assert exc.value.code == "STATE_REPLAY_DRIFT"
