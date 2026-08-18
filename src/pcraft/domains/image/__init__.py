"""The image domain plugin.

Importing this package REGISTERS the plugin (its Generator, tiered Verifiers, and the path to its
generated encoder-craft rules) into the core registry. All torch/diffusion imports are lazy — inside
the verifier/generator methods — so importing the plugin is GPU-free."""

from __future__ import annotations

from pathlib import Path

from ...core.plugin import register

HERE = Path(__file__).parent
RULES_PATH = HERE / "rules" / "encoder_craft.md"
COMPILED_ARTIFACT = HERE / "compiled" / "sprite.synth.v1.json"


class ImagePlugin:
    name = "image"

    def generator(self):
        from .generator.sdxl_generator import SDXLGenerator

        return SDXLGenerator()

    def verifiers(self) -> dict:
        from .verifier.dsg_verifier import DSGVerifier
        from .verifier.palette_verifier import Tier0Router
        from .verifier.vqascore_verifier import VQAScoreVerifier

        return {0: Tier0Router(), 1: VQAScoreVerifier(), 2: DSGVerifier()}

    def encoder_rules_path(self) -> Path:
        return RULES_PATH


register(ImagePlugin())
