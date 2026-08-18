"""Abstention is its own path (F2). The roll-up is not a tier confidence (F1)."""

from __future__ import annotations

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.gate import harness
from pcraft.core.gate.exit_contract import error_from_transcript
from pcraft.core.gate.thresholds import Zone
from pcraft.gate_report import format_transcript
from pcraft.testing import ScriptedVerifier


def test_all_skipped_is_unavailable_not_uncertain(sprite_example):
    """The abstention path has its own Zone. It is not UNCERTAIN wearing a skip."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(dag, "x.png", {1: ScriptedVerifier(lambda _q: None)}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert t.overall is not Zone.UNCERTAIN
    assert error_from_transcript(t).code == "GATE_UNAVAILABLE"


def test_one_mid_band_score_is_uncertain_even_if_the_rest_are_high(sprite_example):
    """Roll-up is not max/mean of scores. Nine confident PASSes do not hide one mid-band."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)

    def scorer(q):
        if q.atom_id == "face":
            return 0.60  # vqa mid-band
        return 0.02 if q.polarity.value == "negate" else 0.99

    t = harness.evaluate(dag, "x.png", {1: ScriptedVerifier(scorer)}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNCERTAIN
    err = error_from_transcript(t)
    assert err is not None and err.code == "PARTIAL_UNCONFIRMED"
    assert err.exit_code == 3


def test_mix_of_pass_and_skip_is_uncertain_not_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)

    def scorer(q):
        if q.atom_id == "face":
            return None
        return 0.02 if q.polarity.value == "negate" else 0.95

    t = harness.evaluate(dag, "x.png", {1: ScriptedVerifier(scorer)}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNCERTAIN
    assert t.could_not_run() is False


def test_partial_printout_leads_with_the_unconfirmed_atom(sprite_example):
    """A PARTIAL report must not read as a wall of PASSes with one asterisk."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(dag, "x.png", {1: ScriptedVerifier({"face": 0.60})}, thresholds, generator_family="stable-diffusion")
    text = format_transcript(t)
    assert "unconfirmed / failed:" in text
    fail_at = text.index("unconfirmed / failed:")
    face_at = text.index("face")
    other_at = text.index("other atoms:")
    assert fail_at < face_at < other_at
    assert "tiers executed:" in text
