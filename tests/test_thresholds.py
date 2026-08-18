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
