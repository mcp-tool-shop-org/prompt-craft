"""The gate's process-exit contract.

Nominated chip: could-not-run and ran-and-failed are different exit codes.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pcraft.cli import app
from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.gate import harness
from pcraft.core.gate.exit_contract import error_from_transcript
from pcraft.core.gate.preflight import preflight_image
from pcraft.core.gate.thresholds import Zone
from pcraft.errors import PromptCraftError
from pcraft.testing import ScriptedVerifier, passing_verifiers, write_solid_png


def test_could_not_run_and_ran_and_failed_are_different_exits(sprite_example):
    """Nominated chip. GATE_UNAVAILABLE must not share an exit code with GATE_FAIL."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    skipped = harness.evaluate(dag, "x.png", {1: ScriptedVerifier(lambda _q: None)}, thresholds, generator_family="stable-diffusion")
    failed = harness.evaluate(dag, "x.png", {1: ScriptedVerifier({"tabard": 0.05})}, thresholds, generator_family="stable-diffusion")
    err_skip = error_from_transcript(skipped)
    err_fail = error_from_transcript(failed)
    assert err_skip is not None and err_fail is not None
    assert err_skip.code == "GATE_UNAVAILABLE"
    assert err_fail.code == "GATE_FAIL"
    assert err_skip.exit_code == 4
    assert err_fail.exit_code == 2
    assert err_skip.exit_code != err_fail.exit_code


def test_a_missing_image_is_not_exit_zero():
    """Could not see the input is exit 4, same bucket as GATE_UNAVAILABLE, not GATE_FAIL."""
    result = CliRunner().invoke(app, ["gate", "E:/nope/does-not-exist.png"])
    assert result.exit_code == 4
    text = (result.stdout or "") + (result.stderr or "")
    assert "IO_GATE_INPUT" in text
    assert "gate overall:" not in text


def test_preflight_refuses_a_directory(tmp_path):
    with pytest.raises(PromptCraftError) as exc:
        preflight_image(tmp_path)
    assert exc.value.code == "IO_GATE_INPUT"


def test_preflight_accepts_a_readable_file(tmp_path):
    path = write_solid_png(tmp_path / "ok.png")
    assert preflight_image(path) == path


def test_unavailable_verifiers_on_a_real_file_are_not_exit_zero(tmp_path):
    """Extras missing is GATE_UNAVAILABLE (4), not FAIL (2) and not a pass (0)."""
    image = write_solid_png(tmp_path / "present.png")
    result = CliRunner().invoke(app, ["gate", str(image)])
    assert result.exit_code == 4
    text = (result.stdout or "") + (result.stderr or "")
    assert "GATE_UNAVAILABLE" in text
    assert "UNAVAILABLE" in text
    assert "tiers executed:" in text


def test_could_not_run_when_every_required_atom_is_skipped(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: None)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.could_not_run() is True
    assert t.overall is Zone.UNAVAILABLE
    err = error_from_transcript(t)
    assert err is not None and err.code == "GATE_UNAVAILABLE"
    assert err.exit_code == 4


def test_a_required_fail_is_gate_fail_not_uncertain(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier({"tabard": 0.05})
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.FAIL
    err = error_from_transcript(t)
    assert err is not None and err.code == "GATE_FAIL"
    assert err.exit_code == 2


def test_an_uncertain_score_after_a_real_run_is_partial(sprite_example):
    """A mid-band score is the human band (exit 3), not 'could not run'."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier({"face": 0.60})  # vqa band is 0.40..0.80
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.could_not_run() is False
    err = error_from_transcript(t)
    assert err is not None and err.code == "PARTIAL_UNCONFIRMED"
    assert err.exit_code == 3


def test_a_clean_pass_has_no_error(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    # Both required tiers registered -- a clean pass must mean the whole gate ran.
    t = harness.evaluate(dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.PASS
    assert t.tier_census.n == t.tier_census.m
    assert error_from_transcript(t) is None
