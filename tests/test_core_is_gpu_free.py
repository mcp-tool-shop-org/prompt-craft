"""The load-bearing proof: importing core/ pulls NO diffusion/torch, and core has no such imports.

This test IS the evidence that DECOMPOSE_BY_SECRETS holds — the GPU secret lives entirely in the
domain plugins, never in the domain-agnostic core."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pcraft.core

CORE_MODULES = [
    "pcraft.core.contract.schema",
    "pcraft.core.contract.loader",
    "pcraft.core.contract.compile_questions",
    "pcraft.core.contract.hash",
    "pcraft.core.gate.thresholds",
    "pcraft.core.gate.holdout",
    "pcraft.core.gate.regrade",
    "pcraft.core.gate.table_tools",
    "pcraft.core.gate.verifier_iface",
    "pcraft.core.gate.family_guard",
    "pcraft.core.gate.harness",
    "pcraft.core.gate.preflight",
    "pcraft.core.gate.exit_contract",
    "pcraft.core.gate.checkpoint",
    "pcraft.core.synth.signature",
    "pcraft.core.synth.visual_inventory",
    "pcraft.core.synth.assert_",
    "pcraft.core.synth.synthesizer_iface",
    "pcraft.core.optimize.artifact",
    "pcraft.core.optimize.compile",
    "pcraft.core.receipt.asset_record",
    "pcraft.core.loop.generator_iface",
    "pcraft.core.loop.compensators",
    "pcraft.core.loop.retry_policy",
    "pcraft.core.loop.orchestrate",
    "pcraft.core.plugin",
]


def test_core_imports_without_gpu_deps():
    """Importing core must not pull torch/diffusers. They may already be
    present when the [image] extra is installed; that is not a core leak."""
    before = {name for name in ("torch", "diffusers") if name in sys.modules}
    for mod in CORE_MODULES:
        importlib.import_module(mod)
    pulled = {name for name in ("torch", "diffusers") if name in sys.modules} - before
    assert not pulled, f"importing core pulled {pulled}"


def test_core_source_has_no_diffusion_imports():
    core_dir = Path(pcraft.core.__file__).parent
    forbidden = ("import torch", "from torch", "import diffusers", "from diffusers")
    offenders = []
    for py in core_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        offenders.extend(f"{py.name}: {bad}" for bad in forbidden if bad in text)
    assert not offenders, f"core/ must be GPU-free but found: {offenders}"
