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


# --------------------------------------------------------------------------------------
# 3b. F-70ea9458 -- the assertion is bound to the VALUES, not only to the label
#
# STABILITY.md promises: the bands "will be retuned. Retuning them is not a breaking change",
# and the compensating guarantee is "a decision made under one table cannot be silently replayed
# under another." Only the label was compared, and nothing binds the label to the numbers -- so a
# retune that forgets the version bump left pcraft replay exiting 0 having asserted a guarantee it
# did not check. Retunes stay allowed; an UNDECLARED retune is now detected.
# --------------------------------------------------------------------------------------


def _retuned(table):
    """The exact experiment from the finding: move vqa from {0.80, 0.40} to {0.20, 0.05},
    change nothing else, leave the version string alone."""
    from pcraft.core.gate.thresholds import Band

    retuned = table.model_copy(deep=True)
    retuned.bands["vqa"] = Band(high=0.20, low=0.05)
    return retuned


def test_a_value_retune_under_the_same_version_is_caught_at_replay(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    store, _r, table, _c = load_sprite_example()
    resolved = store.resolve(res.record.contract_id)
    retuned = _retuned(table)

    assert retuned.version == res.record.thresholds_version, "premise: the label did not move"
    assert retuned.fingerprint() != table.fingerprint(), "the numbers did"

    with pytest.raises(PromptCraftError) as excinfo:
        replay(res.record, resolved, thresholds_version=retuned.version, thresholds=retuned)
    assert excinfo.value.code == "STATE_REPLAY_DRIFT"
    assert "sprite.cal.v1" in str(excinfo.value)
    assert excinfo.value.hint


def test_a_genuine_same_table_replay_stays_silent(tmp_path):
    """A retune is not a breaking change and a matching table must not become one."""
    res = run_mock_loop(records_dir=str(tmp_path))
    store, _r, table, _c = load_sprite_example()
    resolved = store.resolve(res.record.contract_id)
    dag = replay(res.record, resolved, thresholds_version=table.version, thresholds=table)
    assert dag.contract_id == res.record.contract_id


def test_a_receipt_written_before_the_fingerprint_existed_still_replays(tmp_path):
    """The additive-field back-compat pattern the receipt reader already established: absent
    means legacy, and a legacy receipt is checked on the version alone rather than refused."""
    res = run_mock_loop(records_dir=str(tmp_path))
    path = tmp_path / f"{res.record.record_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["thresholds_fingerprint"], "premise: this build stamps one"
    del data["thresholds_fingerprint"]
    path.write_text(json.dumps(data), encoding="utf-8")

    rec = load(path)
    assert rec.thresholds_fingerprint == ""
    store, _r, table, _c = load_sprite_example()
    resolved = store.resolve(rec.contract_id)
    dag = replay(rec, resolved, thresholds_version=table.version, thresholds=_retuned(table))
    assert dag.contract_id == rec.contract_id, "a legacy receipt keeps its old, weaker promise"


def test_the_fingerprint_ignores_fields_that_are_not_the_bands():
    """A retune is a change to bands/default. Editing the notes -- which the shipped table invites
    ('Recalibrate when the generator or verifier checkpoint changes') -- must not read as one."""
    _s, _r, table, _c = load_sprite_example()
    reworded = table.model_copy(deep=True)
    reworded.notes = "reworded, retuned nothing"
    reworded.calibrated_on = "different prose"
    assert reworded.fingerprint() == table.fingerprint()


# --------------------------------------------------------------------------------------
# 4. F-5592ffad -- every coded refusal resolves advice, as a CLASS not as instances
# --------------------------------------------------------------------------------------


def test_the_replay_refusal_surface_all_carries_a_hint():
    """``pcraft replay`` makes exactly three calls that can refuse: asset_record.load
    (IO_RECORD_READ), thresholds.load_thresholds (IO_THRESHOLDS_READ) and asset_record.replay
    (STATE_REPLAY_DRIFT). 100 percent of a covered command's refusal surface shipped with the
    hint field empty, so ``to_safe_text()`` omitted the line entirely."""
    for code in ("IO_RECORD_READ", "IO_THRESHOLDS_READ", "STATE_REPLAY_DRIFT"):
        assert DEFAULT_HINTS.get(code), f"{code} is a reachable refusal with no advice"
        assert "hint:" in PromptCraftError(code, "probe").to_safe_text()
    drift = DEFAULT_HINTS["STATE_REPLAY_DRIFT"].lower()
    assert "re-bind" in drift or "rebind" in drift, "name the recoveries, not just the disagreement"
    assert "not corrupt" in drift


def test_every_error_construction_site_in_src_resolves_a_hint():
    """Close the CLASS, not the three instances. The only hint assertions this domain had each
    pinned one specific code, and the ASCII sweep iterates DEFAULT_HINTS -- i.e. only codes that
    already have hints -- so nothing anywhere would catch the NEXT hintless code.

    Walks every ``PromptCraftError(...)`` / ``wrap_error(...)`` construction in the shipped
    package and asserts the raised error resolves a non-empty ``.hint``, whether from an inline
    argument at the call site or from DEFAULT_HINTS.
    """
    import ast
    import pathlib

    import pcraft

    src = pathlib.Path(pcraft.__file__).resolve().parent
    hintless: dict[str, list[str]] = {}
    seen = 0
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if name == "PromptCraftError":
                code_arg = node.args[0] if node.args else None
                inline = len(node.args) >= 3
            elif name == "wrap_error":
                code_arg = node.args[1] if len(node.args) >= 2 else None
                inline = len(node.args) >= 3
            else:
                continue
            if not isinstance(code_arg, ast.Constant) or not isinstance(code_arg.value, str):
                continue  # a code assembled at runtime; the sweep cannot resolve it statically
            seen += 1
            inline = inline or any(kw.arg == "hint" for kw in node.keywords)
            if inline or DEFAULT_HINTS.get(code_arg.value):
                continue
            hintless.setdefault(code_arg.value, []).append(
                f"{path.relative_to(src).as_posix()}:{node.lineno}"
            )

    assert seen > 20, "the sweep parsed almost nothing; it has drifted off the package"
    assert not hintless, (
        "these coded refusals reach a user with an empty hint line, because to_safe_text() "
        f"omits the line when hint resolves to '': {hintless}"
    )


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


# --------------------------------------------------------------------------- coordinator addition
# (hint-wording family.) Several DEFAULT_HINTS entries named ONLY the editable install --
# ``pip install -e '.[image]'`` -- which is a command that requires a CHECKOUT. A user who ran
# ``pip install prompt-crafter`` has no '.' to point at, so the one actionable sentence those
# refusals give could not be run at all. DEP_IMAGE_MISSING and GATE_UNAVAILABLE are precisely the
# codes that user meets first. Codes and exit codes are untouched; this is about the prose.


def test_no_hint_recommends_the_editable_install_without_the_installed_form():
    """``pip install -e`` presumes a checkout. A hint may still mention it -- contributors exist --
    but never as the only route, and never without saying it is the checkout case."""
    from pcraft.errors import DEFAULT_HINTS

    offenders = {}
    for code, hint in DEFAULT_HINTS.items():
        if "pip install -e" not in hint:
            continue
        names_installed_form = "pip install 'prompt-crafter" in hint or (
            "pip install " in hint.replace("pip install -e", "")
        )
        if not (names_installed_form and "checkout" in hint):
            offenders[code] = hint
    assert not offenders, (
        "these hints tell a pip-installed user to run a command that needs a source checkout, "
        f"and name no alternative: {sorted(offenders)}"
    )


def test_the_install_hints_name_the_distribution_that_actually_publishes():
    """The project is published as ``prompt-crafter``; ``pip install prompt-craft`` installs
    something else or nothing. A hint that names the wrong distribution is worse than none."""
    from pcraft.errors import DEFAULT_HINTS

    wrong = {
        code: hint
        for code, hint in DEFAULT_HINTS.items()
        if "pip install prompt-craft " in hint or hint.rstrip(".").endswith("pip install prompt-craft")
    }
    assert not wrong, f"these name a distribution that is not what pyproject publishes: {sorted(wrong)}"


def test_the_receipt_path_hint_is_backed_by_a_field_that_carries_it():
    """IO_RECORD_READ tells the operator that bind names the receipt it wrote. That sentence was
    once a promise about a path nothing carried: ``persist()`` returned the Path and ``run()``
    dropped it, so the CLI had to re-derive the filename. ``OrchestrationResult.record_path`` is
    what makes the sentence true, so the sentence and the field are pinned together (F-5b783e17).

    The pinned phrase carries Phase 9's F6 refinement: "at the end of every run" was false on
    the could-not-score paths (exit 1 and 4 persist nothing), so the promise is now scoped to
    runs whose loop scored -- and this pin holds the hint to a promise the field can keep."""
    from pcraft.core.loop.orchestrate import OrchestrationResult
    from pcraft.errors import DEFAULT_HINTS

    assert "names the receipt whenever its loop scored" in DEFAULT_HINTS["IO_RECORD_READ"]
    assert "record_path" in OrchestrationResult.model_fields, (
        "the hint claims the path is printed; the result object has to be able to supply it"
    )


# --------------------------------------------------------------------------------------------
# F-9bd8360e -- to_safe_text emitted the hint as one unbroken line regardless of length, so the
# code/message/hint hierarchy the module docstring promises survived exactly one visual line.
# MEASURED over all 43 DEFAULT_HINTS as they actually render (the '  hint: ' prefix included):
# 38 of 43 exceeded 80 columns, 31 of 43 exceeded 120. The worst are the codes an operator hits
# most: GATE_FAIL rendered as a 379-character line, RUNTIME_GENERATE_EXHAUSTED 326,
# RUNTIME_GENERATE_FAILED 287, STATE_REPLAY_DRIFT 282. At 80 columns GATE_FAIL's hint occupied 5
# visual lines of which 4 began at COLUMN 0 -- the same column as 'error[GATE_FAIL]:' -- so the
# two-space indent that distinguishes hint from message was visible only on the first line and
# the advice read as a second error paragraph.
#
# Seven hints additionally ended with a prose 'Exit N.' sentence, so a structured fact this class
# already owns as `exit_code` was buried at the tail of the longest wrapped run instead of being
# its own field on its own line -- and could drift from exit_code_for(), which is the value the
# CLI actually returns.
#
# Fixed width, not terminal-detected, so these assertions and the cp437 ASCII sweep above stay
# deterministic.
# --------------------------------------------------------------------------------------------

_HINT_WIDTH = 80


def test_no_rendered_error_line_overflows_a_standard_terminal():
    from pcraft.errors import DEFAULT_HINTS, PromptCraftError

    offenders = []
    for code in sorted(DEFAULT_HINTS):
        rendered = PromptCraftError(code, "a message of ordinary length").to_safe_text()
        offenders += [
            (code, len(ln)) for ln in rendered.splitlines()[1:] if len(ln) > _HINT_WIDTH
        ]
    assert not offenders, f"hint lines still overflow: {offenders}"


def test_the_hint_block_never_reaches_the_error_column():
    """The two-space indent is the ONLY thing distinguishing advice from the error itself, and
    it survived exactly one visual line."""
    from pcraft.errors import DEFAULT_HINTS, PromptCraftError

    for code in sorted(DEFAULT_HINTS):
        rendered = PromptCraftError(code, "a message of ordinary length").to_safe_text()
        for line in rendered.splitlines()[1:]:
            assert line.startswith("  "), (
                f"{code}: {line!r} renders in the 'error[...]' column, so the advice reads as "
                "a second error paragraph"
            )


def test_a_wrapped_hint_hangs_under_its_own_label():
    from pcraft.errors import PromptCraftError

    lines = PromptCraftError("GATE_FAIL", "required atom 'palette' failed").to_safe_text().splitlines()
    hint_lines = [ln for ln in lines if ln.startswith("  hint:") or ln.startswith(" " * 8)]
    assert len(hint_lines) > 1, "GATE_FAIL's hint is 379 characters; it has to wrap"
    assert hint_lines[0].startswith("  hint: ")
    for line in hint_lines[1:]:
        assert line.startswith(" " * 8), (
            f"a continuation hangs under the label column, not at the margin: {line!r}"
        )
        assert not line.startswith(" " * 9), f"one indent, not a ragged one: {line!r}"


def test_a_multi_sentence_hint_starts_each_sentence_on_a_fresh_line():
    """37 of 43 hints are multi-sentence and 15 carry three or more; read as steps, not prose."""
    from pcraft.errors import PromptCraftError

    lines = PromptCraftError("GATE_FAIL", "required atom 'palette' failed").to_safe_text().splitlines()
    starts = [ln.strip() for ln in lines if ln.startswith(" " * 8) or ln.startswith("  hint:")]
    assert any(s.startswith("If most required atoms are SKIPPED") for s in starts), (
        f"the second sentence must begin a line of its own: {starts}"
    )


def test_the_exit_code_is_its_own_field_not_a_sentence():
    """exit_code_for() computes this; a prose copy in seven hints can only drift from it."""
    from pcraft.errors import DEFAULT_HINTS, PromptCraftError, exit_code_for

    for code in sorted(DEFAULT_HINTS):
        err = PromptCraftError(code, "a message of ordinary length")
        assert f"  exit: {exit_code_for(code)}" in err.to_safe_text().splitlines(), code


def test_no_hint_restates_the_exit_code_in_prose():
    """GATE_FAIL, GATE_UNAVAILABLE, IO_GATE_INPUT, PARTIAL_UNCONFIRMED,
    CONTRACT_CYCLIC_DEPENDS_ON, CONTRACT_SCHEMA_UNSUPPORTED and IO_RECORD_SCHEMA_UNSUPPORTED
    each ended with one. The field above owns the fact now."""
    from pcraft.errors import DEFAULT_HINTS

    offenders = sorted(code for code, hint in DEFAULT_HINTS.items() if "Exit " in hint)
    assert not offenders, f"the exit code is a field, not prose: {offenders}"


def test_the_inline_tier_census_hint_does_not_restate_its_exit_code_either():
    """Not a DEFAULT_HINTS entry, so the sweep above cannot see it -- the same class of miss
    that let F-a6acaab1's em dash survive the wave-2 pass."""
    from pcraft.core.contract.compile_questions import Polarity
    from pcraft.core.contract.schema import Severity
    from pcraft.core.gate.exit_contract import error_from_transcript
    from pcraft.core.gate.harness import AtomVerdict, GateTranscript, TierCensus
    from pcraft.core.gate.thresholds import Zone

    t = GateTranscript(
        contract_id="char:ashen-reaver",
        overall=Zone.PASS,
        verdicts=[
            AtomVerdict(
                atom_id="tabard", polarity=Polarity.affirm, severity=Severity.required,
                score=0.95, zone=Zone.PASS, tier_used=1, tiers_consulted=[1],
                verifier_id="v", reason="score 0.9500 -> PASS",
            )
        ],
        tier_census=TierCensus(required=[0, 1], executed=[1]),
    )
    err = error_from_transcript(t)
    assert err is not None and err.code == "PARTIAL_TIER_CENSUS"
    assert "Exit " not in err.hint, err.hint
    assert "  exit: 3" in err.to_safe_text().splitlines()
