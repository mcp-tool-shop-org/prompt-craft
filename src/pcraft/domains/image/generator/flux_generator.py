"""Flux generator (swappable encoder per the system-architecture reuse slot).

Same plugin contract as SDXL; ``family = "flux"``. A sibling to ``SDXLGenerator`` demonstrating that
the generator is the swappable secret — the core loop, contract, gate, and optimizer are unchanged
when the encoder changes. torch/diffusers are lazy ``[image]`` deps."""

from __future__ import annotations

from pathlib import Path

from ....errors import PromptCraftError
from ....core.loop.generator_iface import GenerationResult


class FluxGenerator:
    generator_id = "flux.1-dev.v1"
    family = "flux"

    def __init__(self, model_id: str = "black-forest-labs/FLUX.1-dev", out_dir: str | Path = "records/_image", steps: int = 28):
        self.model_id = model_id
        self.out_dir = Path(out_dir)
        self.steps = steps
        self._pipe = None

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        try:
            from diffusers import FluxPipeline  # type: ignore
        except Exception as err:
            raise PromptCraftError("DEP_IMAGE_MISSING", "Flux needs the [image] extra (torch + diffusers)") from err
        self._pipe = FluxPipeline.from_pretrained(self.model_id)
        return self._pipe

    def generate(self, prompt: str, negative_prompt: str, conditioning: dict, seed: int) -> GenerationResult:
        pipe = self._load()
        import torch  # type: ignore

        generator = torch.Generator(device=getattr(pipe, "device", "cpu")).manual_seed(seed)
        image = pipe(prompt=prompt, num_inference_steps=self.steps, generator=generator).images[0]
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{self.generator_id}_seed{seed}.png"
        image.save(path)
        return GenerationResult(
            image_path=str(path), seed=seed, sampler="flow-match", generator_id=self.generator_id,
            generator_family=self.family, conditioning=conditioning,
        )
