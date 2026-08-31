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
