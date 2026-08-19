from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pcraft.cli import app
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
    dag = replay(rec, resolved, thresholds_version=rec.thresholds_version)  # no raise == reproduces
    assert dag.contract_id == rec.contract_id


def test_cli_replay_of_invalid_schema_does_not_dump_a_traceback(tmp_path):
    path = tmp_path / "not-a-record.json"
    path.write_text('{"record_id": "only-one-field"}', encoding="utf-8")
    result = CliRunner().invoke(app, ["replay", str(path)])
    assert result.exit_code == 2
    text = (result.stdout or "") + (result.stderr or "")
    assert "IO_RECORD_INVALID" in text
    assert "Traceback" not in text
    assert "pydantic" not in text.lower()


def test_load_rejects_valid_json_that_fails_the_schema(tmp_path):
    """A schema miss is IO_RECORD_INVALID, not a raw pydantic traceback."""
    path = tmp_path / "not-a-record.json"
    path.write_text('{"record_id": "only-one-field"}', encoding="utf-8")
    with pytest.raises(PromptCraftError) as exc:
        load(path)
    assert exc.value.code == "IO_RECORD_INVALID"
    assert "ValidationError" not in exc.value.to_safe_text()


def test_receipt_stores_the_attempt_story(tmp_path):
    """A bind is not just retry_count. The receipt names each generate+gate step."""
    res = run_mock_loop(records_dir=str(tmp_path))
    assert res.record is not None
    assert res.record.attempts
    assert res.record.attempts[0].note == "best-of-N"
    loaded = load(tmp_path / f"{res.record.record_id}.json")
    assert loaded.attempts[0].seed == res.record.attempts[0].seed
    assert loaded.attempts[0].repair is None


def test_escalated_receipt_keeps_repairs_and_the_checkpoint(tmp_path):
    from pcraft.core.loop import orchestrate
    from pcraft.core.loop.orchestrate import LoopConfig
    from pcraft.core.synth.signature import TemplateSynthesizer
    from pcraft.testing import StubGenerator, passing_verifiers

    _s, resolved, thresholds, compiled = load_sprite_example()
    result = orchestrate.run(
        resolved,
        TemplateSynthesizer(compiled),
        StubGenerator(out_dir=tmp_path / "_stub_images"),
        passing_verifiers(scores={"weapon": 0.05}),
        thresholds,
        config=LoopConfig(thresholds_version=thresholds.version, records_dir=str(tmp_path)),
    )
    assert result.decision == "escalated"
    assert result.record is not None
    assert any(a.repair is not None for a in result.record.attempts)
    assert result.record.checkpoint is not None
    loaded = load(tmp_path / f"{result.record.record_id}.json")
    assert loaded.checkpoint is not None
    assert loaded.checkpoint.text == result.record.checkpoint.text


def test_replay_detects_contract_drift(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    store, _r, _t, _c = load_sprite_example()
    resolved = store.resolve(res.record.contract_id)
    resolved.must_have[0].claim = "TAMPERED — the contract changed since bind"
    with pytest.raises(PromptCraftError) as exc:
        replay(res.record, resolved, thresholds_version=None)
    assert exc.value.code == "STATE_REPLAY_DRIFT"
