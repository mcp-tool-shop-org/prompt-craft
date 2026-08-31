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
from pcraft.errors import DEFAULT_HINTS, PromptCraftError, exit_code_for
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
    # F-4846c12e: the code was pinned and the exit code was not, so only half this invariant was
    # proven -- and the unproven half disagreed with its own sibling. STABILITY.md introduces
    # IO_RECORD_SCHEMA_UNSUPPORTED and CONTRACT_SCHEMA_UNSUPPORTED together, as one idea applied
    # to the two on-disk formats, but the IO_ prefix mapped this one to 2 ("prompt-craft
    # crashed") while the contract sibling got 1 ("fix your input") -- pinned at line 102 below
    # with the same reasoning. A file that is perfectly well formed and merely newer is user
    # input. Mirrors that assertion so both halves are proven on both siblings.
    assert exit_code_for(excinfo.value.code) == 1, "a receipt from the future is user input, exit 1"
    # The distinct code has to deliver distinct guidance too. IO_RECORD_INVALID -- the code
    # STABILITY.md says this must not be confused with -- carries a hint telling you to re-bind;
    # this one carried none at all, so to_safe_text() emitted no hint line and the reader was
    # left with the re-bind advice from the code they were explicitly not given.
    assert excinfo.value.hint, "a distinct code with no distinct guidance is half a refusal"
    assert "hint:" in excinfo.value.to_safe_text()
    assert "re-bind" in excinfo.value.hint.lower(), "the actionable half is: do not re-bind this file"


def test_every_error_hint_prints_on_a_legacy_windows_console():
    """F-fd21bd37, this file's family of call sites: every DEFAULT_HINTS value is printed
    verbatim by ``to_safe_text()``, which is the CLI's whole error surface. Three of them carried
    U+2014 EM DASH (GATE_SAME_FAMILY, GATE_UNAVAILABLE, CONTRACT_RELAXATION).

    On a cp437 console -- classic cmd.exe -- that is not mojibake, it is a hard
    UnicodeEncodeError while printing: the error path CRASHES instead of telling the user what
    went wrong, and it crashes hardest on GATE_UNAVAILABLE, whose entire job is to explain a
    could-not-run. Pinned as ASCII rather than merely cp437-encodable, because ASCII is the only
    codepage-independent guarantee and these strings are advice, not typography."""
    offenders: dict[str, str] = {}
    for code, hint in DEFAULT_HINTS.items():
        try:
            hint.encode("ascii")
        except UnicodeEncodeError as err:
            offenders[code] = hint[err.start : err.end]
    assert not offenders, (
        f"DEFAULT_HINTS values must be pure ASCII; these are not: {offenders}. "
        "They print straight to a console whose codepage we do not control."
    )


def test_the_whole_rendered_error_survives_cp437():
    """The end-to-end shape of the same crash: it is the composed to_safe_text() line that gets
    written, not the hint in isolation, so the assertion is made against the real output for
    every code that has a hint."""
    for code in sorted(DEFAULT_HINTS):
        rendered = PromptCraftError(code, "probe message").to_safe_text()
        rendered.encode("cp437")  # raises UnicodeEncodeError if a console could not print it


def test_the_module_docstring_exit_tables_agree_with_the_real_maps():
    """F-a2de5ab2: STABILITY.md was updated for the IO_RECORD_SCHEMA_UNSUPPORTED -> 1 override
    and errors.py was not, so the front-door table in the file that DEFINES the mapping still
    read "IO_ ... -> exit 2", with the correction living only in a comment forty lines below.
    That is the same in-source-vs-front-door drift this repo names commits after -- and the risk
    is a maintainer reading either table and concluding the wrong thing.

    In the same spirit as test_stability_surface_names_resolve.py, this parses the DOCUMENT
    (here, the module docstring) rather than restating it: hard-coding the expected rows would
    let the two drift apart in exactly the way the check exists to prevent. A prefix row ends
    with ``_``; a per-code override does not.
    """
    import re

    import pcraft.errors as errors_module

    rows = re.findall(
        r"^\s{4}([A-Z][A-Z0-9_]*)\s+\S.*?->\s*exit\s+(\d)\s*$",
        errors_module.__doc__ or "",
        re.MULTILINE,
    )
    assert rows, "parsed no exit rows out of the module docstring; the parser has drifted"
    documented_prefixes = {name: int(code) for name, code in rows if name.endswith("_")}
    documented_codes = {name: int(code) for name, code in rows if not name.endswith("_")}

    assert documented_codes == errors_module._EXIT_BY_CODE, (
        "the 'Per-code overrides' block is the only override list a reader of this file will "
        "find; an override missing from it is a front door that lies"
    )
    assert documented_prefixes == errors_module._EXIT_BY_PREFIX, (
        "the namespace table has to name every prefix the mapping actually has"
    )


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
