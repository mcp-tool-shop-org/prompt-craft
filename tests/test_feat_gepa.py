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
from pcraft.core.synth.visual_inventory import InventoryRow, build_inventory
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


def test_missing_dspy_without_a_runner_is_dep_synth(tmp_path, monkeypatch):
    """[synth] may be installed. Force the missing-DSPy door so this test
    cannot launch a live GEPA compile."""
    import pcraft.core.optimize.compile as compile_mod

    def no_dspy(_name):
        raise PromptCraftError(
            "DEP_SYNTH_MISSING",
            "offline compile needs DSPy + an LM backend",
        )

    monkeypatch.setattr(compile_mod, "_default_runner", no_dspy)
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


# ---------------------------------------------------------------------------
# F-4d4b5b17 -- the injected-predictor path runs the SAME anti-prose-dump guard
#
# synthesize() returned self._predictor(...)'s result via model_copy without ever calling
# assert_tokens_trace -- only the real dspy.Predict path (_run_dspy) called it. MEASURED: a
# predictor returning prompt='epic cinematic masterpiece, trending on artstation, 8k,
# hyperdetailed' -- the exact prose-dump shape the guard exists to catch -- plus a FABRICATED
# atom_coverage self-reporting full coverage of atoms the prompt never mentions was ACCEPTED
# with zero refusal.
#
# The sibling guard assert_coverage gives false confidence here: it only checks that the
# SELF-REPORTED coverage phrases are non-empty, never that they relate to the actual prompt
# text. assert_tokens_trace is the only guard that inspects the prompt string itself, and it
# was the one guard this path skipped. Defense in depth: predictor= is test infrastructure
# today, but signature.py's own docstring names an Ollama-Cloud / local-8B backend as the
# intended real integration point for this exact seam, so "test-only" is temporary, not
# structural. The guard is on the OUTPUT; the injection seam itself stays.
# ---------------------------------------------------------------------------


def _prose_dump_predictor(prompt: str, *, honest_inventory: bool = True):
    """A predictor with the failure shape the finding measured: prose the contract never
    asked for, plus coverage that claims every atom is covered anyway."""

    def predictor(res, _rules, _prog):
        inventory = build_inventory(res)
        return SynthResult(
            prompt=prompt,
            negative_prompt="",
            atom_coverage={a.id: a.claim for a in res.must_have},  # fabricated
            visual_inventory=inventory if honest_inventory else [],
            backend="inject",
            degraded=True,
        )

    return predictor


def test_an_injected_predictor_cannot_return_a_prose_dump():
    _s, resolved, _t, compiled = load_sprite_example()
    synth = DSPySynthesizer(
        compiled,
        predictor=_prose_dump_predictor(
            "epic cinematic masterpiece, trending on artstation, 8k, hyperdetailed"
        ),
    )
    with pytest.raises(PromptCraftError) as exc:
        synth.synthesize(resolved, "")
    assert exc.value.code == "SYNTH_PROSE_DUMP"


def test_the_guard_reads_the_contract_not_the_predictors_self_report():
    """The reason the fix recomputes build_inventory(resolved) rather than trusting
    result.visual_inventory: both the inventory and the coverage are predictor-controlled, and
    the finding measured them diverging from the actual prompt text. A predictor that declares
    its prose depictable must be refused on the same evidence as one that does not."""
    _s, resolved, _t, compiled = load_sprite_example()

    def lying_predictor(res, _rules, _prog):
        prose = "epic cinematic masterpiece, trending on artstation"
        return SynthResult(
            prompt=prose,
            negative_prompt="",
            atom_coverage={a.id: a.claim for a in res.must_have},
            # the lie: an inventory row that would make the prose trace to an "atom"
            visual_inventory=[
                InventoryRow(atom_id="ghost", depictable=True, front_load_rank=0, token=prose)
            ],
            backend="inject",
            degraded=True,
        )

    synth = DSPySynthesizer(compiled, predictor=lying_predictor)
    with pytest.raises(PromptCraftError) as exc:
        synth.synthesize(resolved, "")
    assert exc.value.code == "SYNTH_PROSE_DUMP"


def test_an_injected_predictor_returning_real_atom_tokens_still_passes():
    """The collateral guard, and why this costs no GPU and no network: a predictor whose
    prompt is built from the contract's own claims traces by construction."""
    _s, resolved, _t, compiled = load_sprite_example()
    tokens = ", ".join(a.claim for a in resolved.must_have)
    synth = DSPySynthesizer(compiled, predictor=_prose_dump_predictor(tokens))
    result = synth.synthesize(resolved, "")
    assert result.prompt == tokens
    assert result.backend == f"dspy:{compiled.artifact_id}"


def test_dspy_synthesizer_without_dspy_or_predictor_refuses(monkeypatch):
    """[synth] may be installed. Close the DSPy door so this cannot hit a live LM."""
    import pcraft.core.synth.signature as sig

    monkeypatch.setattr(sig, "_HAS_DSPY", False)
    _s, _r, _t, compiled = load_sprite_example()
    with pytest.raises(PromptCraftError) as exc:
        DSPySynthesizer(compiled).synthesize(_r, "")
    assert exc.value.code == "DEP_SYNTH_MISSING"


def test_per_asset_loop_still_uses_the_template():
    _s, resolved, _t, compiled = load_sprite_example()
    result = TemplateSynthesizer(compiled).synthesize(resolved, "")
    assert result.backend == "template"


def test_live_gepa_artifact_is_a_sibling_of_the_seed():
    from pcraft.domains.image import COMPILED_ARTIFACT

    seed = load_pinned(COMPILED_ARTIFACT)
    assert seed.generated_by == "scaffold-seed"
    gepa = load_pinned(COMPILED_ARTIFACT.with_name("sprite.synth.v1-gepa.json"))
    assert gepa.generated_by == "gepa"
    assert gepa.version == "v1-gepa"
    assert gepa.instruction.strip()
    assert gepa.source_hash


def test_gepa_without_a_configured_lm_is_dep_synth():
    from pcraft.core.optimize.compile import _require_lm

    class _Settings:
        lm = None

    class _Dspy:
        settings = _Settings()

    with pytest.raises(PromptCraftError) as exc:
        _require_lm(_Dspy())
    assert exc.value.code == "DEP_SYNTH_MISSING"


def test_gepa_uses_the_configured_lm():
    from pcraft.core.optimize.compile import _require_lm

    class _Settings:
        lm = "ollama_chat/hermes3:8b"

    class _Dspy:
        settings = _Settings()

    assert _require_lm(_Dspy()) == "ollama_chat/hermes3:8b"


def test_cli_compile_without_seed_is_not_a_silent_ok():
    result = runner.invoke(app, ["compile"])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2
    assert "DEP_SYNTH_MISSING" in text or "STATE_COMPILE_NEEDS_GATE" in text
    assert "not wired" not in text.lower()


# ---------------------------------------------------------------------------
# F-4184d73f -- artifact_id must actually distinguish two different compiles
#
# _next_version(optimizer) returned f"v1-{optimizer}" -- a pure function of the optimizer
# NAME. Since artifact_id is f"{program_id}@{version}", the normal iterate-and-recompile
# workflow (change the trainset or the base instruction, re-run gepa) produced two artifacts
# with different instruction/demos/source_hash and the SAME artifact_id -- and that id is
# what every asset receipt carries as the claim "this run is replayable bit-for-bit".
# ---------------------------------------------------------------------------


class _EchoInstruction:
    """Pins the base instruction verbatim, so the test controls the compiled content."""

    def compile(self, *, trainset, gate_metric, base_instruction):
        gate_metric(trainset[0], base_instruction)
        return OptimizedPrompt(instruction=base_instruction, demos=[], metric_calls=1)


def _compile(tmp_path, name, *, base_instruction, trainset, program_id="sprite.synth"):
    return compile_synthesizer(
        trainset,
        lambda _c, _p: 1.0,
        out_path=tmp_path / name,
        program_id=program_id,
        base_instruction=base_instruction,
        runner=_EchoInstruction(),
    )


def test_two_different_compiles_do_not_share_an_artifact_id(tmp_path):
    """The finding's repro: same program_id, same optimizer, different compiled content."""
    _s, resolved, _t, _c = load_sprite_example()
    first = _compile(tmp_path, "a.json", base_instruction="Convert atoms to a prompt.", trainset=[resolved])
    second = _compile(tmp_path, "b.json", base_instruction="Front-load the tabard.", trainset=[resolved])

    assert first.instruction != second.instruction
    assert first.version != second.version
    assert first.artifact_id != second.artifact_id


def test_a_changed_trainset_also_changes_the_artifact_id(tmp_path):
    """The other half of the iterate-and-recompile workflow the finding names."""
    _s, resolved, _t, _c = load_sprite_example()
    trimmed = resolved.model_copy(update={"must_have": list(resolved.must_have[:1])})
    full = _compile(tmp_path, "a.json", base_instruction="Same text.", trainset=[resolved])
    partial = _compile(tmp_path, "b.json", base_instruction="Same text.", trainset=[trimmed])

    assert full.source_hash != partial.source_hash
    assert full.artifact_id != partial.artifact_id


def test_an_identical_compile_still_reproduces_the_same_artifact_id(tmp_path):
    """Determinism is the point, not novelty: the id is a content fingerprint, never a clock
    or a random. Two byte-identical compiles MUST land on the same id or replay is a lie."""
    _s, resolved, _t, _c = load_sprite_example()
    first = _compile(tmp_path, "a.json", base_instruction="Convert atoms to a prompt.", trainset=[resolved])
    second = _compile(tmp_path, "b.json", base_instruction="Convert atoms to a prompt.", trainset=[resolved])

    assert first.artifact_id == second.artifact_id


def test_the_version_still_names_the_optimizer_that_produced_it(tmp_path):
    """Provenance the old scheme did carry, and the fix must not drop."""
    _s, resolved, _t, _c = load_sprite_example()
    prog = _compile(tmp_path, "a.json", base_instruction="x", trainset=[resolved])
    assert prog.version.startswith("v1-gepa")
    assert prog.version != "v1-gepa"


def test_a_pinned_artifact_round_trips_its_distinct_version(tmp_path):
    _s, resolved, _t, _c = load_sprite_example()
    prog = _compile(tmp_path, "a.json", base_instruction="x", trainset=[resolved])
    assert load_pinned(tmp_path / "a.json").artifact_id == prog.artifact_id


# ---------------------------------------------------------------------------
# F-45c39f7d (artifact door) -- load_pinned's model_validate was unguarded too
# ---------------------------------------------------------------------------


def test_a_schema_invalid_pinned_artifact_is_a_structured_refusal(tmp_path):
    """The finding's sibling repro: a pinned artifact with "version": 123 (wrong type) left
    load_pinned as a raw pydantic ValidationError, one line after the JSONDecodeError door
    that already returns the structured shape."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"program_id": "x", "version": 123, "instruction": "y"}), encoding="utf-8"
    )
    with pytest.raises(PromptCraftError) as exc:
        load_pinned(bad)
    assert exc.value.code == "IO_ARTIFACT_INVALID"
    assert exc.value.cause is not None
    assert "version" in exc.value.to_debug_text()


def test_a_pinned_artifact_missing_a_required_field_is_also_structured(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"program_id": "x"}), encoding="utf-8")
    with pytest.raises(PromptCraftError) as exc:
        load_pinned(bad)
    assert exc.value.code == "IO_ARTIFACT_INVALID"


def test_a_valid_pinned_artifact_still_loads(tmp_path):
    """Collateral guard for the new try/except."""
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps({"program_id": "x", "version": "v1-test", "instruction": "y"}),
        encoding="utf-8",
    )
    assert load_pinned(good).artifact_id == "x@v1-test"


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
