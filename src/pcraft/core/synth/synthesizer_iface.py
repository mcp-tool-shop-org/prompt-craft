"""The Synthesizer plugin interface and its result shape.

A synthesizer turns a resolved contract + the domain's encoder rules into a prompt whose every
token traces to a depictable atom. The result carries provenance -- ``backend`` (which LM produced
it) and ``degraded`` (did a cloud->local fallback happen) -- so the loop NEVER silently accepts a
worse proposal."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from ..contract.schema import ResolvedContract
from .visual_inventory import InventoryRow


class SynthResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str
    negative_prompt: str
    atom_coverage: dict[str, str]  # atom_id -> the phrase covering it
    visual_inventory: list[InventoryRow]
    backend: str  # "template" | "cloud:minimax-m3:cloud" | "local:hermes3:8b" ...
    degraded: bool = False


@runtime_checkable
class Synthesizer(Protocol):
    synthesizer_id: str

    def synthesize(self, resolved: ResolvedContract, encoder_rules: str) -> SynthResult: ...
