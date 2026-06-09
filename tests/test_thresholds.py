from __future__ import annotations

from pcraft.core.contract.compile_questions import Polarity
from pcraft.core.gate.thresholds import Zone


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
