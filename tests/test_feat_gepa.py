"""F-OPT-FEAT-001 — offline GEPA + DSPySynthesizer.

GPU-free: inject a runner / predictor. No DSPy, no LM, no diffusion.
The metric is EXTERNAL. The per-asset loop still uses TemplateSynthesizer.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pcraft.cli import app
from pcraft.core.optimize.artifact import load_pinned
from pcraft.core.optimize.compile import OptimizedPrompt, compile_synthesizer
from pcraft.core.synth.signature import DSPySynthesizer, TemplateSynthesizer
from pcraft.core.synth.synthesizer_iface import SynthResult
from pcraft.core.synth.visual_inventory import build_inventory
from pcraft.errors import PromptCraftError
from pcraft.sample import load_sprite_example

runner = CliRunner()


class _BestOfTwo:
    """Picks the instruction the EXTERNAL metric prefers. That is the law."""

    def compile(self, *, trainset, gate_metric, base_instruction):
        a = base_instruction
        b = base_instruction + " Front-load the tabard."
        score_a = gate_metric(trainset[0], a)
        score_b = gate_metric(trainset[0], b)
        chosen = b if score_b >= score_a else a
        return OptimizedPrompt(instruction=chosen, demos=[], metric_calls=2)


def test_compile_pins_gepa_against_the_external_metric(tmp_path):
    _s, resolved, _t, _c = load_sprite_example()
    seen: list[tuple[str, str]] = []

    def metric(contract, prompt):
        seen.append((contract.id, prompt))
        return 0.9 if "tabard" in prompt else 0.1

    out = tmp_path / "sprite.synth.v1.json"
    prog = compile_synthesizer(
        [resolved],
        metric,
        out_path=out,
        program_id="sprite.synth",
        base_instruction="Convert atoms to a prompt.",
        runner=_BestOfTwo(),
    )
    assert prog.generated_by == "gepa"
    assert "tabard" in prog.instruction
    assert prog.source_hash
    assert seen and all(cid == resolved.id for cid, _p in seen)
    loaded = load_pinned(out)
    assert loaded.generated_by == "gepa"
    assert loaded.instruction == prog.instruction


def test_empty_trainset_refuses(tmp_path):
    with pytest.raises(PromptCraftError) as exc:
        compile_synthesizer(
            [],
            lambda _c, _p: 1.0,
            out_path=tmp_path / "x.json",
            program_id="x",
            base_instruction="x",
            runner=_BestOfTwo(),
        )
    assert exc.value.code == "INPUT_EMPTY_STORE"


def test_unknown_optimizer_refuses(tmp_path):
    _s, resolved, _t, _c = load_sprite_example()
    with pytest.raises(PromptCraftError) as exc:
        compile_synthesizer(
            [resolved],
            lambda _c, _p: 1.0,
            out_path=tmp_path / "x.json",
            program_id="x",
            base_instruction="x",
            optimizer="grpo",
            runner=_BestOfTwo(),
        )
    assert exc.value.code == "STATE_COMPILE_NOT_WIRED"


def test_missing_dspy_without_a_runner_is_dep_synth(tmp_path):
    _s, resolved, _t, _c = load_sprite_example()
    with pytest.raises(PromptCraftError) as exc:
        compile_synthesizer(
            [resolved],
            lambda _c, _p: 1.0,
            out_path=tmp_path / "x.json",
            program_id="x",
            base_instruction="x",
        )
    assert exc.value.code == "DEP_SYNTH_MISSING"


def test_dspy_synthesizer_runs_the_pinned_artifact(tmp_path):
    _s, resolved, _t, compiled = load_sprite_example()

    def predictor(res, _rules, prog):
        inventory = build_inventory(res)
        return SynthResult(
            prompt="a grey-ash tabard worn over the torso",
            negative_prompt="",
            atom_coverage={a.id: a.claim for a in res.must_have},
            visual_inventory=inventory,
            backend="inject",
            degraded=True,
        )

    synth = DSPySynthesizer(compiled, predictor=predictor)
    result = synth.synthesize(resolved, "")
    assert result.backend == f"dspy:{compiled.artifact_id}"
    assert result.degraded is False
    assert "tabard" in result.prompt
    assert synth.synthesizer_id.startswith("dspy.v1+")


def test_dspy_synthesizer_without_dspy_or_predictor_refuses():
    _s, _r, _t, compiled = load_sprite_example()
    with pytest.raises(PromptCraftError) as exc:
        DSPySynthesizer(compiled).synthesize(_r, "")
    assert exc.value.code == "DEP_SYNTH_MISSING"


def test_per_asset_loop_still_uses_the_template():
    _s, resolved, _t, compiled = load_sprite_example()
    result = TemplateSynthesizer(compiled).synthesize(resolved, "")
    assert result.backend == "template"


def test_cli_compile_without_seed_is_not_a_silent_ok():
    result = runner.invoke(app, ["compile"])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2
    assert "DEP_SYNTH_MISSING" in text or "STATE_COMPILE_NEEDS_GATE" in text
    assert "not wired" not in text.lower()


def test_cli_compile_seed_still_pins(tmp_path, monkeypatch):
    from pcraft.core.optimize.compile import write_seed_artifact

    written = {}

    def fake_seed(out_path, program_id, instruction):
        written["path"] = str(out_path)
        return write_seed_artifact(tmp_path / "seed.json", program_id, instruction)

    import pcraft.core.optimize.compile as compile_mod

    monkeypatch.setattr(compile_mod, "write_seed_artifact", fake_seed)
    result = runner.invoke(app, ["compile", "--seed"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert written
    data = json.loads((tmp_path / "seed.json").read_text(encoding="utf-8"))
    assert data["generated_by"] == "scaffold-seed"
