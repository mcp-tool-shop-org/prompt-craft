from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pcraft.cli import app
from pcraft.core.receipt.asset_record import load, persist, replay
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


# --------------------------------------------------------------------------- F-a99ec99e
# persist() wrote to a path derived from a non-unique record_id and silently destroyed whatever
# receipt was already there -- including a bound one, on precisely the runs that matter
# (base_seed defaults to 1000 and best-of-N early-exits on the first clean PASS).


def _receipts(d):
    return sorted(p for p in d.glob("*.json"))


def test_a_second_run_cannot_destroy_the_first_bound_receipt(tmp_path):
    """MEASURED as filed: run 1 bound, run 2 escalated, one file on disk reading 'escalated', and
    the gate transcript that justified the bind unrecoverable."""
    first = run_mock_loop(records_dir=str(tmp_path))
    assert first.decision == "bound"
    first_path = tmp_path / f"{first.record.record_id}.json"
    assert first_path.exists()

    second = run_mock_loop(records_dir=str(tmp_path), verifier_scores={"weapon": 0.05})
    assert second.decision == "escalated"

    assert first_path.exists(), "the bound receipt was destroyed by the next run"
    assert load(first_path).decision == "bound"
    assert second.record.record_id != first.record.record_id
    assert len(_receipts(tmp_path)) == 2, "re-binds must accumulate, not replace"


def test_persist_refuses_to_clobber_rather_than_deleting_a_receipt(tmp_path):
    """Residual collisions have to be an ANSWER, not a deletion. compensators registers
    'records-write' with post_state 'receipt deleted by id' and an owner; the deletion this
    door used to perform happened unattended, with no owner and no notice."""
    res = run_mock_loop(records_dir=str(tmp_path))
    path = tmp_path / f"{res.record.record_id}.json"
    before = path.read_text(encoding="utf-8")

    with pytest.raises(PromptCraftError) as exc:
        persist(res.record, tmp_path)
    assert exc.value.code == "IO_RECORD_EXISTS"
    assert exc.value.hint
    assert str(path) in exc.value.message or path.name in exc.value.message
    assert path.read_text(encoding="utf-8") == before, "the refusal must leave the file alone"


# --------------------------------------------------------------------------- F-f99c78f8
# The receipt could not identify the artifact it certifies.


def test_the_receipt_names_the_pixels_it_bound(tmp_path):
    from datetime import datetime

    res = run_mock_loop(records_dir=str(tmp_path))
    rec = load(tmp_path / f"{res.record.record_id}.json")

    assert rec.image_path, "a 'bound' receipt that cannot say which file it scored is not provenance"
    from pathlib import Path

    assert Path(rec.image_path).exists()
    assert rec.prompt, "PIN_PER_STEP is model + PROMPT + tool schema"
    assert datetime.fromisoformat(rec.created_at), "an overwrite is undetectable without a time"
    assert rec.created_at.endswith("Z") or "+00:00" in rec.created_at


def test_compiled_synth_id_is_not_a_second_copy_of_the_backend(tmp_path):
    """Both fields were assigned ``synth.backend`` at the only construction site, so the module
    docstring credited a pinned field that carried no information the field beside it did not."""
    res = run_mock_loop(records_dir=str(tmp_path))
    rec = load(tmp_path / f"{res.record.record_id}.json")
    assert rec.synth_backend == "template"
    assert rec.compiled_synth_id != rec.synth_backend
    assert rec.compiled_synth_id, "the id of the compiled artifact, not a duplicate label"
