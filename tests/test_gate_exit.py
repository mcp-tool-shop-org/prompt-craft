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


def test_missing_vlm_extras_on_a_real_file_are_not_exit_zero(tmp_path):
    """Palette scores without the [image] extra. VQA/SigLIP2 still SKIP.
    That is PARTIAL (3), not a pass (0) and not a required-atom FAIL (2)."""
    image = write_solid_png(tmp_path / "present.png")
    result = CliRunner().invoke(app, ["gate", str(image)])
    assert result.exit_code in {2, 3}
    text = (result.stdout or "") + (result.stderr or "")
    assert "GATE_UNAVAILABLE" not in text
    assert "tiers executed:" in text
    assert "palette" in text.lower()


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


# --------------------------------------------------------------------------- F-2c7b997a
# "this contract declares no required atom" and "no required atom produced a score" are two
# different answers. Merging them sent an operator off installing extras for a run in which
# every verifier scored and every atom passed.


def _all_optional(resolved):
    from pcraft.core.contract.schema import Severity as _Sev

    for atom in resolved.must_have:
        atom.severity = _Sev.optional
    for negation in resolved.must_not:
        negation.severity = _Sev.optional
    return resolved


def test_a_contract_with_no_required_atom_is_not_reported_as_a_missing_verifier(sprite_example):
    """MEASURED as filed: every atom optional, every atom scored, every atom passed -- and the
    exit contract answered GATE_UNAVAILABLE at exit 4, whose hint says to install the [image]
    extra 'so a verifier can score'. Fail-closed is right; that diagnosis is not."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(_all_optional(resolved))
    t = harness.evaluate(dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion")
    assert all(v.zone is Zone.PASS for v in t.verdicts), "premise: the gate ran fully"

    err = error_from_transcript(t)
    assert err is not None, "a contract that can block on nothing must still not read as a pass"
    assert err.code == "CONTRACT_NO_REQUIRED_ATOM"
    assert err.exit_code == 1, "an unblockable contract is user input, not a runtime fault"
    assert err.hint
    assert "install" not in err.hint.lower(), "nothing here is a missing dependency"


def test_a_contract_with_required_atoms_that_never_scored_is_still_gate_unavailable(sprite_example):
    """The other side of the split: the common could-not-run path is untouched."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: None)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.could_not_run() is True
    err = error_from_transcript(t)
    assert err is not None and err.code == "GATE_UNAVAILABLE"
    assert err.exit_code == 4


# --------------------------------------------------------------------------- F-56203d3d
# GATE_FAIL is the gate's entire purpose and the code every content failure lands on, and its
# structured error -- the only thing a CI job, an MCP client or an LLM consumer sees -- said a
# content atom failed and said nothing about a half-installed gate that skipped the other five.
# MEASURED, real ``pcraft gate`` on a stub PNG with no [image] extra: exit 2 with
# ``required atom(s) failed: palette`` on a transcript where four required atoms were SKIPPED
# ('vqascore.clip-flant5.v1 unavailable'), a fifth was NA behind a skipped parent, only ONE of six
# required atoms produced a score at all, and the census line above read 'tiers executed: 1 of 2'.
# That is the plain ``pip install prompt-craft`` experience, not an exotic path.


def _half_installed(resolved, thresholds):
    """Tier-0 present, Tier-1 absent: the shape a missing [image] extra actually produces."""
    tier0 = ScriptedVerifier(
        {"palette": 0.333}, family="siglip2", tier=0, verifier_id="palette.hist.v1"
    )
    dag = compile_questions(resolved)
    return harness.evaluate(
        dag, "x.png", {0: tier0}, thresholds, generator_family="stable-diffusion"
    )


def test_gate_fail_says_how_much_of_the_gate_never_scored(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    err = error_from_transcript(_half_installed(resolved, thresholds))
    assert err is not None and err.code == "GATE_FAIL", "a real FAIL is still a real FAIL"
    assert "palette" in err.message, "the failed atom is still named first"
    assert "5 of 6" in err.message, (
        "one required atom of six produced a score; the structured error said nothing about "
        "the other five"
    )
    assert "SKIPPED" in err.message and "NA" in err.message
    assert "tabard" in err.message and "sigil" in err.message


def test_gate_fail_carries_the_tier_census_it_was_decided_under(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    err = error_from_transcript(_half_installed(resolved, thresholds))
    assert "1 of 2" in err.message, "the census line is printed above; the error dropped it"


def test_gate_fail_hint_names_a_next_move(sprite_example):
    """The hint was 'A failed required atom blocks. Identity still gates nothing.' -- sentence one
    restates the code, sentence two is project jargon (the identity_subgate fence) answering a
    question the operator did not ask. There was no next move at all."""
    _s, resolved, thresholds, _c = sprite_example
    err = error_from_transcript(_half_installed(resolved, thresholds))
    hint = err.hint.lower()
    assert "severity" in hint, "lowering the atom's severity in the contract is one real move"
    assert "[image]" in hint or "pip install" in hint, (
        "a gate whose atoms are mostly SKIPPED is half-installed, not a content failure"
    )
    # Phase 9 (F2): the old hint said "install the [image] extra" to a user whose doctor
    # already read "[image] present" -- the actual missing packages were the model-tier
    # verifier imports no extra declares. The hint must name the packages and the command
    # that diagnoses them, or the next move is a circle.
    assert "t2v-metrics" in hint and "ai-eyes-mcp" in hint, (
        "the hint stopped naming the model-tier packages the [image] extra does not carry"
    )
    assert "doctor" in hint, "pcraft doctor is the diagnosis; the hint has to send them there"
    assert "identity still gates nothing" not in hint, (
        "the identity_subgate fence is not an operator-facing next move"
    )


def test_a_fully_scored_failure_does_not_claim_a_half_installed_gate(sprite_example):
    """The common case must not grow census prose it did not earn: every required atom scored,
    both tiers ran, one atom failed."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", passing_verifiers(scores={"weapon": 0.05}), thresholds,
        generator_family="stable-diffusion",
    )
    err = error_from_transcript(t)
    assert err is not None and err.code == "GATE_FAIL"
    assert "weapon" in err.message
    assert "produced no score" not in err.message, "every required atom scored on this run"
    assert "2 of 2" in err.message or "tiers" not in err.message


def test_the_gate_fail_exit_code_is_unchanged(sprite_example):
    """Widening the message and the hint may not move the number a CI branch reads."""
    from pcraft.errors import exit_code_for

    _s, resolved, thresholds, _c = sprite_example
    err = error_from_transcript(_half_installed(resolved, thresholds))
    assert exit_code_for(err.code) == 2
