"""The Generator plugin interface.

A generator turns a prompt + assembled conditioning into pixels. The contract NAMES the
conditioning (``spatial.pose`` -> ControlNet; ``identity_ref`` -> IP-Adapter/LoRA); the generator
ASSEMBLES it. The result pins everything needed to reproduce the render (seed, sampler, generator
id, the conditioning inputs actually used) for the receipt."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_path: str
    seed: int
    sampler: str
    generator_id: str
    generator_family: str  # must differ from every gate verifier family (family_guard)
    conditioning: dict = {}  # the controlnet/ip-adapter inputs actually applied


@runtime_checkable
class Generator(Protocol):
    generator_id: str
    family: str

    def generate(
        self,
        prompt: str,
        negative_prompt: str,
        conditioning: dict,
        seed: int,
    ) -> GenerationResult: ...
