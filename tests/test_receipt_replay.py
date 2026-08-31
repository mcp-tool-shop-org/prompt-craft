from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pcraft.cli import app
from pcraft.core.contract.hash import contract_hash
from pcraft.core.gate.thresholds import Zone
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


# --------------------------------------------------------------------------- F-dec37d4e
# Offline re-grade. The four refusals above are the ONLY feedback the product gave about a
# retune: STATE_REPLAY_DRIFT says the table moved and names neither an atom nor a direction.
# Every input needed to answer the question is already on the receipt -- per-atom score,
# band_key, polarity and severity on each AtomVerdict -- and ThresholdTable.zone() is the
# exact function that graded it the first time. These pin the read that turns the refusal
# into an answer, and pin that it stays a READ: replay still refuses, nothing is re-stamped.


def _regraded(tmp_path, **bands):
    """A bound receipt re-graded under a candidate table. Returns (report, record, candidate)."""
    from pcraft.core.gate.regrade import regrade

    record, _resolved, table = _bound(tmp_path)
    candidate = _retuned(table, **bands)
    return regrade(record, candidate), record, candidate


def test_a_candidate_table_names_the_atoms_that_flip_and_the_direction(tmp_path):
    """MEASURED as filed: moving vqa from 0.80/0.40 to 0.96/0.40 takes five required atoms of an
    asset already in canon from PASS to UNCERTAIN. The shipped product answered that question
    with STATE_REPLAY_DRIFT, which names neither an atom nor a direction."""
    report, record, _candidate = _regraded(tmp_path, vqa=(0.96, 0.40))

    flipped = {a.atom_id: (a.was.value, a.now.value) for a in report.flips}
    assert flipped == {
        "tabard": ("PASS", "UNCERTAIN"),
        "sigil": ("PASS", "UNCERTAIN"),
        "skin": ("PASS", "UNCERTAIN"),
        "weapon": ("PASS", "UNCERTAIN"),
        "face": ("PASS", "UNCERTAIN"),
    }
    assert len(report.blocking_flips) == 5, "every one of them is severity=required"
    assert report.record_id == record.record_id
    assert report.contract_id == record.contract_id
    text = report.summary()
    assert "tabard" in text and "PASS -> UNCERTAIN" in text and "5 blocking" in text


def test_the_regraded_overall_reuses_the_gate_own_rollup_and_exit_contract(tmp_path):
    """MUST NOT BREAK (4): a second roll-up implementation would drift from the gate it claims
    to predict. The new overall comes from harness's own _rollup over the re-zoned verdicts, and
    the code from exit_contract -- the same two functions the live gate uses."""
    from pcraft.core.gate.exit_contract import error_from_transcript
    from pcraft.core.gate.harness import _rollup
    from pcraft.core.gate.regrade import regrade_transcript

    report, record, candidate = _regraded(tmp_path, vqa=(0.96, 0.40))
    rebuilt = regrade_transcript(record.gate_transcript, candidate, dag=record.question_dag)

    assert report.was_overall is Zone.PASS and report.now_overall is Zone.UNCERTAIN
    assert rebuilt.overall is _rollup(rebuilt.verdicts), "not a second roll-up"
    err = error_from_transcript(rebuilt)
    assert err is not None and err.code == "PARTIAL_UNCONFIRMED"
    assert report.now_code == "PARTIAL_UNCONFIRMED"
    assert report.was_code == "", "the receipt as decided was a clean pass; '' is that answer"


def test_the_re_derived_census_matches_the_one_the_gate_recorded(tmp_path):
    """A table cannot change which tiers executed. Re-deriving it from the stored DAG rather
    than copying the stored census is what PROVES that, instead of asserting it."""
    from pcraft.core.gate.regrade import regrade_transcript

    record, _resolved, table = _bound(tmp_path)
    rebuilt = regrade_transcript(
        record.gate_transcript, _retuned(table, vqa=(0.96, 0.40)), dag=record.question_dag
    )
    assert rebuilt.tier_census == record.gate_transcript.tier_census
    assert rebuilt.thresholds_version == table.version


def test_a_regrade_is_a_read_and_leaves_the_receipt_exactly_as_it_found_it(tmp_path):
    """MUST NOT BREAK (3): schema_version '1' is a covered reader, and this path must not write,
    re-stamp or migrate. Bytes on disk and the in-memory record are both pinned."""
    from pcraft.core.gate.regrade import regrade, regrade_dir

    res = run_mock_loop(records_dir=str(tmp_path))
    path = tmp_path / f"{res.record.record_id}.json"
    before = path.read_bytes()
    _s, _r, table, _c = load_sprite_example()

    report = regrade(res.record, _retuned(table, vqa=(0.96, 0.40)))
    regrade_dir(tmp_path, _retuned(table, vqa=(0.96, 0.40)))

    assert path.read_bytes() == before, "a re-grade that rewrites the receipt is not a read"
    assert res.record.thresholds_version == table.version, "the record was not re-stamped"
    assert all(v.zone is Zone.PASS for v in res.record.gate_transcript.verdicts if v.score)
    assert report.now_overall is Zone.UNCERTAIN, "the answer lives in the report, not the receipt"


def test_the_regrade_answers_the_question_replay_still_refuses(tmp_path):
    """MUST NOT BREAK (2): STATE_REPLAY_DRIFT does not become a warning. The new verb reports;
    replay keeps refusing the same way, on the same table, in the same run."""
    from pcraft.core.gate.regrade import regrade

    record, resolved, table = _bound(tmp_path)
    candidate = _retuned(table, vqa=(0.96, 0.40))

    with pytest.raises(PromptCraftError) as exc:
        replay(record, resolved, thresholds_version=None, thresholds=candidate)
    assert exc.value.code == "STATE_REPLAY_DRIFT"

    report = regrade(record, candidate)
    assert report.from_fingerprint == record.thresholds_fingerprint
    assert report.to_fingerprint == candidate.fingerprint()
    assert report.from_fingerprint != report.to_fingerprint


def test_a_table_whose_values_did_not_move_reports_no_flips(tmp_path):
    """The other direction: a candidate that changes nothing must say so, not manufacture noise."""
    from pcraft.core.gate.regrade import regrade

    record, _resolved, table = _bound(tmp_path)
    report = regrade(record, table)
    assert report.flips == []
    assert report.blocking_flips == []
    assert report.was_overall is report.now_overall is Zone.PASS
    assert report.was_code == report.now_code == ""
    assert "no verdict moves" in report.summary()


def test_an_atom_that_never_scored_is_carried_not_guessed(tmp_path):
    """A re-grade cannot resurrect a score the gate never took. An atom whose parent blocked it
    carries no number, so no table can move it -- and saying that out loud is the difference
    between a report and a confident invention."""
    from pcraft.core.gate.regrade import regrade

    res = run_mock_loop(records_dir=str(tmp_path), verifier_scores={"tabard": 0.05})
    _s, _r, table, _c = load_sprite_example()
    record = res.record
    unscored = [v.atom_id for v in record.gate_transcript.verdicts if v.score is None]
    assert unscored, "premise: a failed parent forces at least one atom to NA"

    report = regrade(record, _retuned(table, vqa=(0.96, 0.40)))
    assert report.carried == unscored
    assert all(a.atom_id not in unscored for a in report.atoms)
    assert "carried" in report.summary()


def test_a_receipt_written_before_the_fingerprint_existed_still_regrades(tmp_path):
    """Absent means legacy, the same back-compat rule the receipt reader established. A re-grade
    is a read of scores; it needs no fingerprint to do its job."""
    import json as _json

    from pcraft.core.gate.regrade import regrade

    res = run_mock_loop(records_dir=str(tmp_path))
    path = tmp_path / f"{res.record.record_id}.json"
    data = _json.loads(path.read_text(encoding="utf-8"))
    del data["thresholds_fingerprint"]
    path.write_text(_json.dumps(data), encoding="utf-8")

    _s, _r, table, _c = load_sprite_example()
    report = regrade(load(path), _retuned(table, vqa=(0.96, 0.40)))
    assert report.from_fingerprint == ""
    assert len(report.blocking_flips) == 5


def test_a_records_dir_is_swept_in_one_read(tmp_path):
    """The retune question is asked about a CORPUS, not about one asset."""
    from pcraft.core.gate.regrade import regrade_dir

    first = run_mock_loop(records_dir=str(tmp_path))
    second = run_mock_loop(records_dir=str(tmp_path), verifier_scores={"weapon": 0.05})
    _s, _r, table, _c = load_sprite_example()

    reports = regrade_dir(tmp_path, _retuned(table, vqa=(0.96, 0.40)))
    assert {r.record_id for r in reports} == {first.record.record_id, second.record.record_id}
    assert sum(len(r.blocking_flips) for r in reports) > 0


# --------------------------------------------------------------------------------------
# F-b0e6dde7 -- the receipt index. The provenance data existed and nothing read it in
# aggregate: persist() writes one file, load() reads one path, replay() checks one record.
# The only approach was a shell loop over `pcraft replay`, which is all-or-nothing -- the
# first drifted receipt exits 2 and the loop tells you nothing about the rest.
# --------------------------------------------------------------------------------------


def _two_receipts(tmp_path):
    bound = run_mock_loop(records_dir=str(tmp_path))
    escalated = run_mock_loop(records_dir=str(tmp_path), verifier_scores={"weapon": 0.05})
    return bound, escalated


def test_scan_lists_every_receipt_and_keys_on_contents_not_filenames(tmp_path):
    """The receipt FILENAME is not a covered surface -- _record_id pushes everything through
    _fs_safe, and its docstring records an NTFS alternate-data-stream near-miss. The index is
    keyed on record CONTENTS."""
    from pcraft.core.receipt.index import scan

    bound, escalated = _two_receipts(tmp_path)
    renamed = tmp_path / "not-the-record-id.json"
    (tmp_path / f"{bound.record.record_id}.json").rename(renamed)

    index = scan(tmp_path)
    by_id = {r.record_id: r for r in index.rows}
    assert set(by_id) == {bound.record.record_id, escalated.record.record_id}
    assert by_id[bound.record.record_id].path == str(renamed)
    assert by_id[bound.record.record_id].decision == "bound"
    assert by_id[escalated.record.record_id].decision == "escalated"
    assert by_id[bound.record.record_id].contract_hash == bound.record.contract_hash
    assert by_id[bound.record.record_id].image_path == bound.record.image_path


def test_an_unreadable_receipt_is_a_row_not_the_end_of_the_report(tmp_path):
    """"The first bad file ends the report" is the exact failure the shell-loop workaround has.
    A damaged receipt is reported AS a row, with its own code, and the scan keeps going."""
    from pcraft.core.receipt.index import scan

    bound, _escalated = _two_receipts(tmp_path)
    (tmp_path / "damaged.json").write_text('{"record_id": "only-one-field"}', encoding="utf-8")

    index = scan(tmp_path)
    assert len(index.rows) == 3
    assert len(index.readable()) == 2, "two good receipts still reported"
    bad = index.unreadable()
    assert len(bad) == 1
    assert bad[0].code == "IO_RECORD_INVALID"
    assert bad[0].record_id == "", "an unreadable file has no id; the filename is not one"
    assert bad[0].path.endswith("damaged.json")
    assert bound.record.record_id in {r.record_id for r in index.readable()}


def test_a_receipt_from_the_future_keeps_its_own_code_in_the_listing(tmp_path):
    """"Written by a newer prompt-craft" is not "corrupt", and the listing must not merge them."""
    import json

    from pcraft.core.receipt.index import scan

    bound, _e = _two_receipts(tmp_path)
    path = tmp_path / f"{bound.record.record_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = "99"
    path.write_text(json.dumps(data), encoding="utf-8")

    codes = {r.code for r in scan(tmp_path).unreadable()}
    assert codes == {"IO_RECORD_SCHEMA_UNSUPPORTED"}


def test_scan_writes_nothing_back_into_the_records_dir(tmp_path):
    """The index must be a DERIVED read, never a file written back into records_dir where it
    could collide with a receipt path (persist()'s O_EXCL) or be mistaken for one."""
    from pcraft.core.receipt.index import scan

    _two_receipts(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    scan(tmp_path)
    scan(tmp_path).summary()
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_scan_refuses_a_records_dir_that_does_not_exist(tmp_path):
    """A typo'd directory must not read as "you have no receipts"."""
    from pcraft.core.receipt.index import scan

    with pytest.raises(PromptCraftError) as exc:
        scan(tmp_path / "no-such-dir")
    assert exc.value.code == "INPUT_RECORDS_DIR"
    assert exc.value.exit_code == 1


def test_an_existing_but_empty_records_dir_is_an_empty_listing_not_a_refusal(tmp_path):
    from pcraft.core.receipt.index import scan

    index = scan(tmp_path)
    assert index.rows == []
    assert index.summary().total == 0


def test_the_query_filters_on_fields_that_exist_on_receipts(tmp_path):
    from pcraft.core.receipt.index import RecordQuery, scan

    bound, escalated = _two_receipts(tmp_path)
    index = scan(tmp_path)

    only_bound = index.query(RecordQuery(decision="bound"))
    assert [r.record_id for r in only_bound] == [bound.record.record_id]

    same_contract = index.query(RecordQuery(contract=bound.record.contract_id))
    assert len(same_contract) == 2

    none = index.query(RecordQuery(contract="char:nobody"))
    assert none == []

    by_table = index.query(RecordQuery(thresholds_version=bound.record.thresholds_version))
    assert len(by_table) == 2

    assert index.query(RecordQuery(since="2099-01-01")) == []
    assert len(index.query(RecordQuery(since="2000-01-01"))) == 2
    assert escalated.record.record_id in {r.record_id for r in index.rows}


def test_stale_is_a_comparison_against_todays_contract_hash(tmp_path):
    """"Which receipts are now stale against today's contract" had no mechanical answer. The
    comparison is a pure read against a hash the caller supplies -- the index resolves nothing
    and re-hashes nothing behind the operator's back."""
    from pcraft.core.receipt.index import RecordQuery, scan

    bound, _e = _two_receipts(tmp_path)
    index = scan(tmp_path)
    cid = bound.record.contract_id

    fresh = index.query(RecordQuery(stale_against={cid: bound.record.contract_hash}))
    assert fresh == []
    stale = index.query(RecordQuery(stale_against={cid: "sha256:something-else"}))
    assert len(stale) == 2

    store, _r, _t, _c = load_sprite_example()
    resolved = store.resolve(cid)
    assert contract_hash(resolved) == bound.record.contract_hash, "premise: nothing drifted yet"


def test_the_summary_always_reports_what_could_not_be_read(tmp_path):
    """A filter must never be able to hide the fact that files in this directory did not load."""
    from pcraft.core.receipt.index import RecordQuery, scan

    _two_receipts(tmp_path)
    (tmp_path / "damaged.json").write_text("{", encoding="utf-8")

    index = scan(tmp_path)
    summary = index.summary()
    assert summary.total == 3
    assert summary.readable == 2 and summary.unreadable == 1
    assert summary.codes == {"IO_RECORD_READ": 1}
    assert summary.by_decision == {"bound": 1, "escalated": 1}
    assert summary.latest >= summary.earliest != ""
    assert index.query(RecordQuery(decision="bound")) != index.rows
    assert index.summary().unreadable == 1, "the summary is of the DIRECTORY, not of the filter"


def test_the_index_and_the_regrade_sweep_walk_the_directory_the_same_way(tmp_path):
    """One walk, owned by the module that writes the files it walks. Two spellings of "every
    receipt under this directory" would drift the first time either was edited."""
    from pcraft.core.receipt.asset_record import receipt_paths
    from pcraft.core.receipt.index import scan

    _two_receipts(tmp_path)
    (tmp_path / "_stub_images").mkdir(exist_ok=True)
    assert [str(p) for p in receipt_paths(tmp_path)] == [r.path for r in scan(tmp_path).rows]
