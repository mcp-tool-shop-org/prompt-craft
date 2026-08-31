from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pcraft.core.contract.compile_questions import Polarity
from pcraft.core.gate.thresholds import Band, Zone, load_thresholds
from pcraft.errors import PromptCraftError


def test_affirm_zones(sprite_example):
    _s, _r, thresholds, _c = sprite_example
    # vqa band high=0.80 low=0.40
    assert thresholds.zone("vqa", 0.95, Polarity.affirm) is Zone.PASS
    assert thresholds.zone("vqa", 0.60, Polarity.affirm) is Zone.UNCERTAIN
    assert thresholds.zone("vqa", 0.10, Polarity.affirm) is Zone.FAIL


def test_negate_inverts(sprite_example):
    _s, _r, thresholds, _c = sprite_example
    # a must_not: a HIGH 'is it present?' score is a FAIL (forbidden thing present)
    assert thresholds.zone("vqa", 0.95, Polarity.negate) is Zone.FAIL
    assert thresholds.zone("vqa", 0.02, Polarity.negate) is Zone.PASS
    assert thresholds.zone("vqa", 0.60, Polarity.negate) is Zone.UNCERTAIN


def test_unknown_key_uses_default(sprite_example):
    _s, _r, thresholds, _c = sprite_example
    # default high=0.70 low=0.40
    assert thresholds.zone("made-up", 0.71, Polarity.affirm) is Zone.PASS


# --------------------------------------------------------------------------- F-GATE-FEAT-002 Band invariants


def test_inverted_band_is_refused():
    with pytest.raises(ValidationError):
        Band(high=0.2, low=0.5)


def test_band_outside_unit_interval_is_refused():
    with pytest.raises(ValidationError):
        Band(high=1.2, low=0.1)
    with pytest.raises(ValidationError):
        Band(high=0.8, low=-0.1)


def test_equal_high_and_low_is_allowed():
    band = Band(high=0.5, low=0.5)
    assert band.high == band.low == 0.5


def test_load_thresholds_wraps_an_inverted_band(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "version": "bad.v1",
                "bands": {"vqa": {"high": 0.2, "low": 0.8}},
                "default": {"high": 0.7, "low": 0.4},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PromptCraftError) as exc:
        load_thresholds(path)
    assert exc.value.code == "CONFIG_THRESHOLDS_INVALID"
    assert exc.value.exit_code == 1
    # The one shape the old literal actually described must keep describing itself.
    assert "band" in exc.value.message
    assert "vqa" in exc.value.message


# --------------------------------------------------------------------------- F-3637b97f
# The calibration table is the third on-disk format this product reads and was the only one with
# no forward-compatibility path: a table from a NEWER build was reported as a broken one, with a
# hint that prescribed recalibrating a table that is not miscalibrated.


def _shipped_table() -> dict:
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    return json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def test_a_table_with_no_schema_marker_is_read_as_v1():
    """Absent means v1, exactly as the receipt reader already does -- every calibration file on
    disk (the shipped one included) keeps loading."""
    from pcraft.core.gate.thresholds import THRESHOLDS_SCHEMA_ID
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    assert "$schema" not in _shipped_table(), "premise: the shipped table carries no marker yet"
    table = load_thresholds(THRESHOLDS_PATH)
    assert table.version == "sprite.cal.v1"
    assert table.schema_id == THRESHOLDS_SCHEMA_ID


def test_a_table_from_the_future_is_refused_as_unsupported_not_as_miscalibrated(tmp_path):
    """A copy of the real shipped table with a plausible future field and a newer $schema. Every
    band in it is valid; reporting 'failed band invariants (high >= low)' and telling the operator
    to recalibrate is a wrong diagnosis pointing at the wrong repair."""
    data = _shipped_table()
    data["$schema"] = "prompt-craft/thresholds.v99"
    data["min_scored_atoms"] = 2
    path = tmp_path / "future.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PromptCraftError) as exc:
        load_thresholds(path)
    assert exc.value.code == "CONFIG_THRESHOLDS_SCHEMA_UNSUPPORTED"
    assert exc.value.exit_code == 1
    assert "prompt-craft/thresholds.v99" in exc.value.message
    assert exc.value.hint, "a distinct code with no distinct guidance is half a refusal"
    assert "upgrade" in exc.value.hint.lower()
    # The old hint's whole defect was sending the operator to recalibrate a good table. The new
    # one has to say the opposite out loud, the way IO_RECORD_SCHEMA_UNSUPPORTED says "do NOT
    # re-bind" -- its explicit purpose being to stop the destructive action.
    assert "do not recalibrate" in exc.value.hint.lower()


def test_an_unknown_field_does_not_read_as_a_band_invariant_failure(tmp_path):
    """One literal for every ValidationError meant a typo'd key was reported as a band problem."""
    data = _shipped_table()
    data["min_scored_atoms"] = 2
    path = tmp_path / "extra.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PromptCraftError) as exc:
        load_thresholds(path)
    assert exc.value.code == "CONFIG_THRESHOLDS_INVALID"
    assert "min_scored_atoms" in exc.value.message
    assert "high >= low" not in exc.value.message


def test_a_missing_required_key_reads_as_missing(tmp_path):
    data = _shipped_table()
    del data["default"]
    path = tmp_path / "nodefault.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PromptCraftError) as exc:
        load_thresholds(path)
    assert exc.value.code == "CONFIG_THRESHOLDS_INVALID"
    assert "default" in exc.value.message
    assert "high >= low" not in exc.value.message


def test_a_missing_table_names_where_the_default_one_lives(tmp_path):
    """F-5592ffad: 100% of `pcraft replay`'s refusal surface shipped with an empty hint."""
    with pytest.raises(PromptCraftError) as exc:
        load_thresholds(tmp_path / "nope.json")
    assert exc.value.code == "IO_THRESHOLDS_READ"
    assert exc.value.hint
    assert "--thresholds" in exc.value.hint


# --------------------------------------------------------------------------- coordinator addition
# (F-eaa870d6 family, the same delimiter collision core-contract-synth fixed in loader.py.)
# ``_describe`` joined its per-error aggregate with "; " -- a sequence that also occurs INSIDE a
# pydantic ``msg``, because a msg is free text written by whichever validator raised. So an entry
# containing a semicolon was indistinguishable from the boundary between two entries. The shape
# converged on across the package: an explicit "[n]" index per entry, " | " between them.


def _table_with(**overrides) -> dict:
    data = _shipped_table()
    data.update(overrides)
    return data


def test_an_aggregate_of_several_errors_is_unambiguously_delimited(tmp_path):
    data = _shipped_table()
    del data["default"]
    data["bands"]["vqa"]["high"] = 4.0
    path = tmp_path / "twobad.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PromptCraftError) as exc:
        load_thresholds(path)
    message = exc.value.message
    assert exc.value.code == "CONFIG_THRESHOLDS_INVALID"
    assert "[1] " in message and "[2] " in message, "each entry has to announce its own start"
    assert " | " in message, "the aggregate separator is ' | ', not '; '"
    assert "error(s)" in message, "say how many, the way the loader's sibling does"
    assert "default" in message and "vqa" in message


def test_an_entry_whose_own_message_contains_a_semicolon_is_not_split_by_it():
    """The collision itself. ``msg`` is free text from whichever validator raised -- this file
    does not own those sentences -- so an entry containing '; ' used to be indistinguishable from
    the boundary between two entries, for a reader and for a script alike."""
    from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

    from pcraft.core.gate.thresholds import _describe

    class _Semicoloned(BaseModel):
        model_config = ConfigDict(extra="forbid")
        version: str = ""

        @model_validator(mode="after")
        def _always_objects(self):
            raise ValueError("band high is unset; low is unset; neither can be defaulted")

    with pytest.raises(ValidationError) as exc:
        _Semicoloned()
    rendered = _describe(exc.value)

    assert "; " in rendered, "the fixture's own sentence is the thing under test; keep it intact"
    assert rendered.count(" | ") == 0, "one error is one entry, whatever punctuation it contains"
    assert rendered.split(" | ") == [rendered], "splitting on the real separator yields one entry"


def test_one_error_still_reads_as_one_error(tmp_path):
    """The single-entry case must not grow a separator it does not need."""
    data = _shipped_table()
    del data["default"]
    path = tmp_path / "onebad.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PromptCraftError) as exc:
        load_thresholds(path)
    assert " | " not in exc.value.message
    assert "[1] " in exc.value.message
    assert "1 error(s)" in exc.value.message


# --------------------------------------------------------------------------- F-1d76b4ba
# Retuning is a hand-edit of JSON with no tool between the operator and a table that is loaded
# at gate time. Three questions nothing answered: does this table declare the bands the gate
# will actually look up; what is this candidate's fingerprint (the string a VALUE-drift refusal
# quotes and no command prints); and did the values move without the version moving.
#
# The fence this tooling is built inside: band VALUES stay data (STABILITY.md), so a lint may
# refuse a structurally unusable table and may NEVER refuse a number the author meant; the lint
# lives at AUTHORING time and `band_for`'s gate-time fall to `default` is untouched; and a new
# refusal takes a NEW code rather than widening one of the three covered ones.


def _shipped_path():
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    return THRESHOLDS_PATH


_SHIPPED = _shipped_path()


def _typo_table():
    """The measured case: a table declaring 'vqua' where the gate will look up 'vqa'."""
    from pcraft.core.gate.thresholds import ThresholdTable

    data = _shipped_table()
    data["bands"]["vqua"] = data["bands"].pop("vqa")
    return ThresholdTable.model_validate(data)


def test_a_band_key_the_gate_will_look_up_and_the_table_does_not_declare_is_a_lint_finding():
    """A table declaring 'vqua' returns band_for('vqa') -> default, so a score that would be
    UNCERTAIN under the real 0.80/0.40 band grades PASS under the shipped 0.70/0.40 default --
    no error, no warning, and nothing in the transcript saying the default was used, because
    band_key records the KEY that was looked up and not that the lookup missed.

    [!] The finding illustrated this with a score of 0.55, and 0.55 does NOT demonstrate it:
    under 0.70/0.40 it is UNCERTAIN and under 0.80/0.40 it is UNCERTAIN, so nothing moves. The
    two bands share a low, so the window where they disagree is exactly [0.70, 0.80) -- the
    numbers below are measured against the shipped table rather than restated from the report,
    which is the whole discipline this package is about."""
    from pcraft.core.gate.table_tools import lint

    table = _typo_table()
    assert table.band_for("vqa") is table.default, "premise: the lookup silently misses"
    assert table.zone("vqa", 0.75) is Zone.PASS, "a mid-band score reads as a clean pass"
    assert load_thresholds(_SHIPPED).zone("vqa", 0.75) is Zone.UNCERTAIN, "the real band's answer"

    problems = lint(table)
    assert problems and all(isinstance(p, str) for p in problems)
    joined = "\n".join(problems)
    assert "vqa" in joined, "name the key the gate will look up"
    assert "vqua" in joined, "and the dead one beside it -- together they spell the typo"
    assert "default" in joined, "say what happens instead: a silent fall to `default`"


def test_the_shipped_table_lints_clean():
    """The refusal is only worth anything if the accepted value is the one actually shipped."""
    from pcraft.core.gate.table_tools import lint
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    assert lint(load_thresholds(THRESHOLDS_PATH)) == []


def test_the_needed_keys_are_derived_from_the_check_type_enum_not_hardcoded():
    """A CheckType added tomorrow must widen the lint by itself; a hardcoded list would leave the
    new check_type falling to `default` with nothing saying so -- the exact defect being fixed."""
    from pcraft.core.contract.schema import CheckType
    from pcraft.core.gate.table_tools import needed_band_keys

    assert needed_band_keys() == frozenset(ct.value for ct in CheckType)


def test_lint_never_objects_to_a_value_the_author_meant():
    """STABILITY.md: the bands are data and they will be retuned. A structurally complete table
    lints clean no matter how far the numbers move -- a lint that argued with a number would be
    a promise about values that this project explicitly does not make."""
    from pcraft.core.gate.table_tools import lint
    from pcraft.core.gate.thresholds import Band, ThresholdTable

    wild = ThresholdTable(
        version="wild.v1",
        bands={"vqa": Band(high=0.01, low=0.0), "siglip2": Band(high=1.0, low=1.0),
               "palette": Band(high=0.5, low=0.5)},
        default=Band(high=0.0, low=0.0),
    )
    assert lint(wild) == []


def test_check_refuses_a_structurally_unusable_table_under_its_own_code():
    """F-09f30018's ruling: one covered, machine-parseable code may not carry two unrelated
    meanings. CONFIG_THRESHOLDS_INVALID means "your table is broken"; this means "your table
    parses and the gate will not find the bands in it"."""
    from pcraft.core.gate.table_tools import check

    with pytest.raises(PromptCraftError) as exc:
        check(_typo_table())
    assert exc.value.code == "CONFIG_THRESHOLDS_UNUSABLE"
    assert exc.value.code != "CONFIG_THRESHOLDS_INVALID"
    assert exc.value.exit_code == 1
    assert exc.value.hint
    assert "vqa" in exc.value.message and "vqua" in exc.value.message
    exc.value.to_safe_text().encode("ascii")


def test_the_lint_lives_at_authoring_time_and_the_loader_is_untouched(tmp_path):
    """MUST NOT BREAK: the three covered codes keep their meanings, so the same file that `check`
    refuses must still LOAD -- it is a well-formed table, and load_thresholds does not lint."""
    from pcraft.core.gate.table_tools import lint

    data = _shipped_table()
    data["bands"]["vqua"] = data["bands"].pop("vqa")
    path = tmp_path / "typo.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    table = load_thresholds(path)  # no raise: nothing about this file is malformed
    assert table.version == "sprite.cal.v1"
    assert lint(table), "the lint is the thing that has an opinion, and only when asked"


def test_band_for_still_falls_to_default_at_gate_time():
    """MUST NOT BREAK (3): an unknown key at GATE time is a runtime path with its own
    compatibility story. Turning band_for into a raise is not what this feature is."""
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    table = load_thresholds(THRESHOLDS_PATH)
    assert table.band_for("a-key-no-table-declares") is table.default
    assert table.zone("a-key-no-table-declares", 0.71) is Zone.PASS


def test_diff_says_the_values_changed_and_the_version_did_not():
    """The exact undeclared retune the fingerprint exists to catch, stated as a sentence rather
    than as two hex strings a reader has to compare by eye."""
    from pcraft.core.gate.table_tools import diff
    from pcraft.core.gate.thresholds import Band
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    before = load_thresholds(THRESHOLDS_PATH)
    after = before.model_copy(deep=True)
    after.bands["vqa"] = Band(high=0.20, low=0.05)

    d = diff(before, after)
    assert d.values_changed is True
    assert d.version_changed is False
    assert d.undeclared_retune is True
    assert [r.key for r in d.retuned] == ["vqa"]
    assert (d.added, d.removed, d.default_retuned) == ([], [], False)
    assert "values changed" in d.summary() and "version did NOT" in d.summary()
    d.summary().encode("ascii")


def test_a_declared_retune_is_not_reported_as_an_undeclared_one():
    """The other direction. Retuning bands is not a breaking change and must not read as an
    accusation when the author did the declaring half too."""
    from pcraft.core.gate.table_tools import diff
    from pcraft.core.gate.thresholds import Band
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    before = load_thresholds(THRESHOLDS_PATH)
    after = before.model_copy(deep=True)
    after.bands["vqa"] = Band(high=0.20, low=0.05)
    after.version = "sprite.cal.v2"

    d = diff(before, after)
    assert (d.values_changed, d.version_changed, d.undeclared_retune) == (True, True, False)
    assert "undeclared" not in d.summary()


def test_diff_reads_values_changed_off_the_fingerprint_and_never_a_second_hash():
    """The values-hash already exists and every receipt is compared against it on replay. A
    second content hash here would be a second answer to one question, free to disagree."""
    import inspect

    from pcraft.core.gate import table_tools
    from pcraft.core.gate.table_tools import diff
    from pcraft.core.gate.thresholds import Band
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    src = inspect.getsource(table_tools)
    assert "hashlib" not in src and "sha256" not in src, "reuse fingerprint(); do not re-hash"

    before = load_thresholds(THRESHOLDS_PATH)
    for mutate in (
        lambda t: t.bands.__setitem__("vqa", Band(high=0.2, low=0.05)),
        lambda t: t.bands.__setitem__("brand-new", Band(high=0.2, low=0.05)),
        lambda t: t.bands.pop("palette"),
        lambda t: setattr(t, "default", Band(high=0.9, low=0.1)),
        lambda t: setattr(t, "notes", "reworded, retuned nothing"),
    ):
        after = before.model_copy(deep=True)
        mutate(after)
        d = diff(before, after)
        assert d.values_changed == (before.fingerprint() != after.fingerprint())
        structural = bool(d.added or d.removed or d.retuned or d.default_retuned)
        assert structural == d.values_changed, (
            "the structural lists ARE the explanation of the fingerprint difference; if they "
            "can disagree with it, one of the two is lying"
        )


def test_a_candidate_table_can_state_the_fingerprint_a_drift_refusal_quotes():
    """An operator who gets a VALUE-drift refusal quoting sha256:046b2426e843c106 had no command
    that tells them what a candidate table's fingerprint is."""
    from pcraft.core.gate.table_tools import describe
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    table = load_thresholds(THRESHOLDS_PATH)
    text = describe(table)
    assert table.fingerprint() in text, "the exact string a receipt is compared against"
    assert table.version in text
    assert "$schema" in text or table.schema_id in text, (
        "the two version-shaped strings mean different things; a reader has to see both"
    )
    text.encode("ascii")


# --------------------------------------------------------------------------- F-6f6fc50e
# The human-labelled holdout workflow -- the calibration the shipped data file explicitly
# instructs and the product provided no tooling for. sprite.calibration.json's `calibrated_on`
# reads, verbatim: "GENERIC SEED - not a real human-labelled holdout. Recalibrate against
# ~50-100 labelled sprites per check_type before any canon bind." Grepped src/ at the time of
# the finding: no holdout / labelled / ground-truth / agreement tooling existed anywhere; the
# only hits were the docstrings saying it does not exist.
#
# The fence: this is the WORKFLOW only. The report RECOMMENDS and never writes a table (band
# values stay data). It reads receipts and never re-stamps one. It runs on scores, so core
# stays GPU-free -- producing the scores live is the operator's act with [image] installed.


def _rows(spec):
    """(atom, label, score) triples -> ScoredRow list, all on one band and one contract."""
    from pcraft.core.gate.holdout import ScoredRow

    return [
        ScoredRow(
            image=f"{atom}-{i}.png", contract="char:example", atom=atom,
            label=label, score=score, band_key=band,
        )
        for i, (atom, label, score, band) in enumerate(spec)
    ]


def _jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


_GOOD_MANIFEST = [
    {"image": "a.png", "contract": "char:example", "atom": "tabard", "label": "present"},
    {"image": "b.png", "contract": "char:example", "atom": "tabard", "label": "absent"},
    {"image": "c.png", "contract": "char:example", "atom": "sigil", "label": "borderline"},
]


def test_the_manifest_is_jsonl_with_exactly_the_four_seam_fields(tmp_path):
    """THE SEAM. The image domain writes this file and imports this loader; the field set is the
    agreement between the two domains and is asserted here so neither can widen it alone."""
    from pcraft.core.gate.holdout import MANIFEST_FIELDS, Label, load_manifest

    assert MANIFEST_FIELDS == ("image", "contract", "atom", "label")
    rows = load_manifest(_jsonl(tmp_path / "m.jsonl", _GOOD_MANIFEST))
    assert [r.atom for r in rows] == ["tabard", "tabard", "sigil"]
    assert [r.label for r in rows] == [Label.present, Label.absent, Label.borderline]
    assert set(rows[0].model_dump()) == set(MANIFEST_FIELDS), "no field the seam did not agree"


def test_a_malformed_row_is_refused_by_name_and_by_line_number(tmp_path):
    """A JSONL loader that says "this file is bad" has told the operator nothing: the whole
    reason to use one line per record is that a defect has an address."""
    from pcraft.core.gate.holdout import load_manifest

    cases = {
        "not json": "{not json at all}",
        "unknown label": json.dumps({**_GOOD_MANIFEST[0], "label": "maybe"}),
        "missing field": json.dumps({"image": "a.png", "contract": "c", "atom": "t"}),
        "extra field": json.dumps({**_GOOD_MANIFEST[0], "score": 0.9}),
        "not an object": json.dumps(["a.png", "c", "t", "present"]),
        "empty atom": json.dumps({**_GOOD_MANIFEST[0], "atom": ""}),
    }
    for name, bad in cases.items():
        path = _jsonl(tmp_path / "bad.jsonl", [])
        path.write_text(
            json.dumps(_GOOD_MANIFEST[0]) + "\n" + bad + "\n" + json.dumps(_GOOD_MANIFEST[1]),
            encoding="utf-8",
        )
        with pytest.raises(PromptCraftError) as exc:
            load_manifest(path)
        assert exc.value.code == "INPUT_HOLDOUT_ROW", name
        assert exc.value.exit_code == 1, name
        assert "row 2" in exc.value.message, f"{name}: name the line, not just the file"
        assert exc.value.hint, name
        exc.value.to_safe_text().encode("ascii")


def test_a_manifest_that_cannot_be_read_and_one_with_nothing_in_it_are_different_answers(tmp_path):
    """"You pointed at nothing" and "there is nothing to calibrate on" have nothing in common as
    recoveries -- the same split IO_RECORD_READ / INPUT_EMPTY_STORE already draw."""
    from pcraft.core.gate.holdout import load_manifest

    with pytest.raises(PromptCraftError) as missing:
        load_manifest(tmp_path / "nope.jsonl")
    assert missing.value.code == "IO_HOLDOUT_READ"
    assert missing.value.hint

    with pytest.raises(PromptCraftError) as empty:
        load_manifest(_jsonl(tmp_path / "empty.jsonl", []))
    assert empty.value.code == "INPUT_HOLDOUT_EMPTY"
    assert empty.value.exit_code == 1
    assert empty.value.hint


def test_the_scored_companion_is_the_manifest_row_plus_a_score_and_the_band_that_graded_it(tmp_path):
    """The second half of the seam: what the image domain emits after a verifier pass."""
    from pcraft.core.gate.holdout import (
        MANIFEST_FIELDS,
        SCORED_FIELDS,
        load_manifest,
        load_scored,
        write_scored,
    )

    scored_fields = SCORED_FIELDS
    assert scored_fields == (*MANIFEST_FIELDS, "score", "band_key")
    rows = _rows([("tabard", "present", 0.95, "vqa"), ("tabard", "absent", 0.05, "vqa")])
    path = write_scored(rows, tmp_path / "scored.jsonl")
    back = load_scored(path)
    assert [r.model_dump() for r in back] == [r.model_dump() for r in rows]
    assert set(back[0].model_dump()) == set(SCORED_FIELDS)

    # The two formats are two formats. Reading one as the other is a named refusal, not a guess.
    with pytest.raises(PromptCraftError) as exc:
        load_manifest(path)
    assert exc.value.code == "INPUT_HOLDOUT_ROW"
    with pytest.raises(PromptCraftError):
        load_scored(_jsonl(tmp_path / "m.jsonl", _GOOD_MANIFEST))


def test_the_separation_report_shows_each_label_class_and_where_a_band_would_sit():
    """The report the calibration instruction asks for: per band, what the humans said, what the
    instrument scored, and the two numbers that would separate them."""
    from pcraft.core.gate.holdout import separation_report

    rows = _rows([
        ("tabard", "present", 0.95, "vqa"), ("sigil", "present", 0.88, "vqa"),
        ("skin", "present", 0.90, "vqa"), ("weapon", "absent", 0.05, "vqa"),
        ("face", "absent", 0.20, "vqa"), ("cape", "borderline", 0.55, "vqa"),
    ])
    report = separation_report(rows)
    assert report.rows == 6
    band = next(b for b in report.bands if b.band_key == "vqa")
    assert band.counts == {"present": 3, "absent": 2, "borderline": 1}
    present = next(c for c in band.classes if c.label == "present")
    assert (present.lo, present.p50, present.hi) == (0.88, 0.90, 0.95)
    assert band.separates is True
    assert band.recommended is not None
    assert (band.recommended.high, band.recommended.low) == (0.88, 0.20)
    assert band.borderline_outside == [], "0.55 lands in the uncertain gap, which is the point"


def test_classes_that_overlap_refuse_to_recommend_rather_than_splitting_the_difference():
    """No band separates these, and inventing one would be the report making up calibration --
    the one thing a recommendation must never do."""
    from pcraft.core.gate.holdout import separation_report

    rows = _rows([
        ("a", "present", 0.40, "vqa"), ("b", "present", 0.45, "vqa"),
        ("c", "absent", 0.60, "vqa"), ("d", "absent", 0.30, "vqa"),
    ])
    band = separation_report(rows).bands[0]
    assert band.separates is False
    assert band.recommended is None
    assert band.overlap, "say WHY there is no recommendation"
    assert "0.6" in band.overlap and "0.4" in band.overlap, "name the two scores that cross"
    assert "recommended" not in band.to_dict(), "omit the key rather than emitting a null"


def test_a_holdout_report_recommends_and_never_writes_a_table():
    """MUST NOT BREAK (3): the band values stay data. A report that could write a calibration
    file would turn a recommendation into a decision nobody made."""
    import inspect

    from pcraft.core.gate import holdout

    src = inspect.getsource(holdout)
    assert "ThresholdTable(" not in src, "a recommendation is not a constructed table"
    assert "persist" not in src, "and it never touches the receipt writer"
    public_writers = [
        n for n in holdout.__all__ if n.startswith(("write_", "dump_", "save_", "emit_"))
    ]
    assert public_writers == ["dump_scored", "write_scored"], (
        "the only thing this module writes is the scored companion to the manifest it was "
        f"handed; it must never gain a path that writes a calibration table: {public_writers}"
    )


def test_agreement_names_the_dangerous_class_a_candidate_table_would_admit():
    """A holdout is not a score, it is a disagreement map. The class that matters is the one
    where the humans said ABSENT and the table says PASS: confident acceptance of a miss."""
    from pcraft.core.gate.holdout import agreement
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    table = load_thresholds(THRESHOLDS_PATH)  # vqa 0.80 / 0.40
    rows = _rows([
        ("ok_present", "present", 0.95, "vqa"),
        ("ok_absent", "absent", 0.05, "vqa"),
        ("ok_border", "borderline", 0.60, "vqa"),
        ("bad_absent", "absent", 0.95, "vqa"),
        ("bad_present", "present", 0.10, "vqa"),
    ])
    report = agreement(rows, table)
    assert report.version == table.version
    assert report.fingerprint == table.fingerprint()
    assert report.rows == 5 and report.agree == 3
    band = report.bands[0]
    assert [r.image for r in band.absent_but_pass] == ["bad_absent-3.png"]
    assert [r.image for r in band.present_but_fail] == ["bad_present-4.png"]


def test_a_sweep_ranks_candidate_tables_over_one_labelled_corpus_with_no_verifier_rerun():
    """The whole point of reusing the re-grade primitive: N candidate tables cost N passes over
    a list of floats, not N GPU runs. The best table for this corpus is the one whose band
    actually separates it."""
    from pcraft.core.gate.holdout import sweep
    from pcraft.core.gate.thresholds import Band, ThresholdTable

    rows = _rows([
        ("a", "present", 0.75, "vqa"), ("b", "present", 0.78, "vqa"),
        ("c", "absent", 0.30, "vqa"), ("d", "absent", 0.35, "vqa"),
    ])

    def table(version, high, low):
        return ThresholdTable(
            version=version, bands={"vqa": Band(high=high, low=low)},
            default=Band(high=0.7, low=0.4),
        )

    baseline = table("cal.v1", 0.80, 0.40)  # every present lands UNCERTAIN
    entries = sweep(
        rows,
        {"tight": baseline, "fitted": table("cal.v2", 0.75, 0.35), "loose": table("cal.v3", 0.9, 0.05)},
        baseline=baseline,
    )
    by_name = {e.name: e for e in entries}
    assert by_name["fitted"].agree == 4, "the fitted band agrees with every human label"
    assert by_name["tight"].agree < 4
    assert entries[0].name == "fitted", "best agreement first"
    assert by_name["tight"].flips == 0, "the baseline against itself moves nothing"
    # Both presents move UNCERTAIN -> PASS; both absents were FAIL under 0.40 and stay FAIL
    # under 0.35. Two rows move, and the count is of rows whose ZONE changed -- not of rows
    # whose agreement changed, which is a different question the `agree` column answers.
    assert by_name["fitted"].flips == 2


def test_scores_can_come_from_receipts_already_on_disk(tmp_path):
    """The records source. A labelled corpus is scored ONCE; every candidate table after that is
    a read of receipts, which is the same primitive the offline re-grade is built on."""
    from pcraft.core.gate.holdout import HoldoutRow, scored_from_records
    from pcraft.sample import run_mock_loop

    res = run_mock_loop(records_dir=str(tmp_path))
    rec = res.record
    labelled = [
        HoldoutRow(image=rec.image_path, contract=rec.contract_id, atom="tabard", label="present"),
        HoldoutRow(image=rec.image_path, contract=rec.contract_id, atom="palette", label="present"),
        HoldoutRow(image=rec.image_path, contract=rec.contract_id, atom="ghost", label="absent"),
    ]
    result = scored_from_records(labelled, [rec])
    assert [(r.atom, r.score, r.band_key) for r in result.scored] == [
        ("tabard", 0.95, "vqa"), ("palette", 0.95, "palette"),
    ]
    assert [r.atom for r in result.unscored] == ["ghost"], (
        "a labelled row no receipt scored is reported, never guessed at"
    )


def test_reading_receipts_for_a_holdout_leaves_every_one_of_them_untouched(tmp_path):
    """MUST NOT BREAK (5): a holdout report must not re-stamp or re-decide an existing receipt."""
    from pcraft.core.gate.holdout import HoldoutRow, scored_from_records
    from pcraft.sample import run_mock_loop

    res = run_mock_loop(records_dir=str(tmp_path))
    path = tmp_path / f"{res.record.record_id}.json"
    before = path.read_bytes()
    scored_from_records(
        [HoldoutRow(image=res.record.image_path, contract=res.record.contract_id,
                    atom="tabard", label="present")],
        [res.record],
    )
    assert path.read_bytes() == before
    assert res.record.gate_transcript.verdicts[0].zone is Zone.PASS


def test_the_seam_stays_reachable_under_the_name_its_consumer_probes_for():
    """This format has a consumer in another domain, and that consumer resolves the reader BY
    NAME at import time rather than importing it directly -- so the two halves could land in
    either order. That makes the module path and the reader's name load-bearing in a way an
    ordinary function name is not: renaming either breaks a package that this file cannot see.

    The probe list below is the agreement, restated here rather than imported: reaching into a
    domain package from a core test would create exactly the dependency edge the seam exists to
    avoid, and would make this test pass for the wrong reason if that consumer moved.
    """
    import importlib
    from collections.abc import Mapping

    module = importlib.import_module("pcraft.core.gate.holdout")
    probed = ("load_holdout", "load_manifest", "load_rows", "read_holdout")
    assert any(hasattr(module, n) for n in probed), (
        f"the consumer refuses by name when the module exposes none of {list(probed)}"
    )

    # It also reads each row through a getattr/Mapping shim and stringifies the label before
    # testing it against its own ("present", "absent", "borderline"). A StrEnum satisfies that;
    # a plain Enum would stringify to "Label.present" and fail the membership test on their side
    # with nothing on this side going red.
    row = holdout_module_row()
    for key in ("image", "contract", "atom", "label"):
        value = row.get(key) if isinstance(row, Mapping) else getattr(row, key, None)
        assert value not in (None, ""), key
    assert str(row.label) == "present", "str(label) is what the consumer compares; keep it bare"


def holdout_module_row():
    from pcraft.core.gate.holdout import HoldoutRow

    return HoldoutRow(image="a.png", contract="char:x", atom="tabard", label="present")


def test_the_labelled_format_is_domain_neutral_and_names_no_example():
    """MUST NOT BREAK (2): STABILITY.md excludes the sprite subdomain from every promise, so the
    labelled-set format must not quietly become a claim about it. `contract`, `atom` and
    `band_key` are free strings; nothing here knows what a sprite is."""
    import inspect

    from pcraft.core.gate import holdout

    src = inspect.getsource(holdout)
    for name in ("sprite", "ashen", "domains", "subdomains"):
        assert name not in src, f"the seam format must not reference {name!r}"
    # The substantive half: no import edge to any domain, and no default that would make one
    # domain's ids the format's ids. A labelled set the image domain writes and this package
    # reads has to be readable by a domain that does not exist yet.
    assert all(
        not str(f.default).startswith(("char:", "faction:"))
        for model in (holdout.HoldoutRow, holdout.ScoredRow)
        for f in model.model_fields.values()
    )
