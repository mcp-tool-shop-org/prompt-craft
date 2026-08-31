from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pcraft.cli import app
from pcraft.core.contract.hash import contract_hash
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


# --------------------------------------------------------------------------- F-154dd9b2
# STATE_REPLAY_DRIFT is four different refusals, and all four raise sites passed no inline hint,
# so every one resolved the same DEFAULT_HINTS entry -- whose LEAD remedy ("re-run replay with
# --thresholds pointed at the table the receipt names") is IMPOSSIBLE for the value-drift arm
# (both tables call themselves the same version, so it names the very file that just failed) and
# IRRELEVANT for the two contract arms (--thresholds cannot affect them at all). The code stays
# one code -- STABILITY.md says parse the code, not the prose -- and each site states its own
# recovery, the way preflight.py already gives its three IO_GATE_INPUT sites three different ones.


def _bound(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    store, _r, table, _c = load_sprite_example()
    return res.record, store.resolve(res.record.contract_id), table


def _retuned(table, **bands):
    """A table that keeps the version string and moves the numbers -- the undeclared retune."""
    copy = table.model_copy(deep=True)
    for key, (high, low) in bands.items():
        copy.bands[key].high, copy.bands[key].low = high, low
    return copy


def test_value_drift_does_not_tell_the_operator_to_point_at_the_file_that_just_failed(tmp_path):
    """The arm whose whole premise is that BOTH tables call themselves 'sprite.cal.v1'."""
    record, resolved, table = _bound(tmp_path)
    with pytest.raises(PromptCraftError) as exc:
        replay(record, resolved, thresholds_version=None, thresholds=_retuned(table, vqa=(0.20, 0.05)))
    err = exc.value
    assert err.code == "STATE_REPLAY_DRIFT"
    assert "--thresholds" not in err.hint or "cannot" in err.hint, (
        "following the generic hint re-runs the identical command for the identical refusal"
    )
    assert "re-bind" in err.hint.lower(), "keep the retune, bump the version, re-bind"
    assert "restore" in err.hint.lower(), "or restore the bands this receipt was decided under"
    assert record.thresholds_fingerprint in err.hint or record.thresholds_fingerprint in err.message


def test_contract_hash_drift_names_both_hashes_and_the_contract(tmp_path):
    """The most reachable arm of the four -- contracts are edited constantly and calibration
    tables almost never are -- and the whole message was 'contract hash drift for <id>: the
    contract changed since this asset was bound': neither hash, no revision, not even the
    contract id, while the two threshold arms beside it print both sides."""
    record, resolved, _table = _bound(tmp_path)
    resolved.must_have[0].claim = "TAMPERED -- the contract changed since bind"
    with pytest.raises(PromptCraftError) as exc:
        replay(record, resolved, thresholds_version=None)
    err = exc.value
    assert err.code == "STATE_REPLAY_DRIFT"
    assert record.contract_id in err.message, "name the contract, not only the record"
    assert record.contract_hash in err.message, "the receipt's side of the comparison"
    assert contract_hash(resolved) in err.message, "and this run's side"
    assert "--thresholds" in err.hint, "say the flag does not apply, rather than leading with it"
    assert "does not affect" in err.hint or "cannot affect" in err.hint


def test_dag_drift_says_the_contract_did_not_change(tmp_path):
    """Reached only when the contract hash MATCHED and compile_questions still produced a
    different DAG -- so the only realistic cause is a prompt-craft VERSION change, which the
    generic hint never mentions."""
    record, resolved, _table = _bound(tmp_path)
    tampered = record.model_copy(deep=True)
    tampered.question_dag.questions[0].text = "a question this build does not compile"
    with pytest.raises(PromptCraftError) as exc:
        replay(tampered, resolved, thresholds_version=None)
    err = exc.value
    assert err.code == "STATE_REPLAY_DRIFT"
    assert "version" in err.hint.lower(), "a DAG that differs under a matching hash is a build change"
    assert "--thresholds" not in err.hint


def test_version_drift_keeps_the_remedy_that_actually_applies(tmp_path):
    """The one arm the generic hint WAS written for keeps it: two different version strings, so
    pointing --thresholds at the table the receipt names is a real move."""
    record, resolved, _table = _bound(tmp_path)
    with pytest.raises(PromptCraftError) as exc:
        replay(record, resolved, thresholds_version="sprite.cal.v2")
    err = exc.value
    assert err.code == "STATE_REPLAY_DRIFT"
    assert "--thresholds" in err.hint
    assert record.thresholds_version in err.message and "sprite.cal.v2" in err.message


def test_all_four_arms_still_answer_with_one_parseable_code_and_four_hints(tmp_path):
    """STABILITY.md's contract: the CODE is the machine surface and does not fork. The prose is
    what the operator reads, and four refusals with four recoveries may not share one sentence."""
    record, resolved, table = _bound(tmp_path)
    tampered_contract = resolved.model_copy(deep=True)
    tampered_contract.must_have[0].claim = "TAMPERED"
    tampered_dag = record.model_copy(deep=True)
    tampered_dag.question_dag.questions[0].text = "not what this build compiles"

    cases = [
        lambda: replay(record, resolved, thresholds_version="sprite.cal.v2"),
        lambda: replay(record, resolved, thresholds_version=None,
                       thresholds=_retuned(table, vqa=(0.20, 0.05))),
        lambda: replay(record, tampered_contract, thresholds_version=None),
        lambda: replay(tampered_dag, resolved, thresholds_version=None),
    ]
    hints = []
    for case in cases:
        with pytest.raises(PromptCraftError) as exc:
            case()
        assert exc.value.code == "STATE_REPLAY_DRIFT"
        assert exc.value.hint, "a refusal with no advice is half a refusal"
        exc.value.to_safe_text().encode("ascii")
        hints.append(exc.value.hint)
    assert len(set(hints)) == 4, f"one hint serving four refusals: {sorted(set(hints))}"
