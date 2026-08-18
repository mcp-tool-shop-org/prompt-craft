"""Smoke tests for the image plugin: it registers and BUILDS without a GPU.

These catch import-path bugs in the plugin modules (construction is GPU-free; only .score/.generate
touch torch). Without the [image] extra, the real verifiers SKIP gracefully — never crash."""

from __future__ import annotations

import pcraft.domains.image  # noqa: F401  (importing registers the plugin)
from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.plugin import get, registered
from pcraft.sample import load_sprite_example


def test_image_plugin_registers():
    assert "image" in registered()


def test_image_plugin_builds_without_gpu():
    plugin = get("image")
    verifiers = plugin.verifiers()
    assert set(verifiers) == {0, 1, 2}
    families = {v.family for v in verifiers.values()}
    assert "siglip2" in families and "clip-flant5" in families and "dsg-qg" in families
    gen = plugin.generator()
    assert gen.family == "stable-diffusion"  # distinct from every verifier family


def test_image_encoder_rules_are_generated_from_readouts():
    path = get("image").encoder_rules_path()
    assert path.exists(), "encoder_craft.md missing — run scripts/sync_rules_from_readouts.py"
    text = path.read_text(encoding="utf-8")
    assert "GENERATED FILE" in text
    assert "prompt-craft" in text  # the lane it was synced from


def test_real_verifier_skips_gracefully_without_models():
    _store, resolved, _t, _c = load_sprite_example()
    dag = compile_questions(resolved)
    vqascore = get("image").verifiers()[1]
    # the [image] extra isn't installed in the core env -> the verifier returns None (SKIPPED)
    assert vqascore.score("nonexistent.png", dag.questions[0]) is None
