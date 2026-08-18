"""Flux generator (swappable encoder per the system-architecture reuse slot).

Same plugin contract as SDXL; ``family = "flux"``. A sibling to ``SDXLGenerator`` demonstrating that
the generator is the swappable secret -- the core loop, contract, gate, and optimizer are unchanged
when the encoder changes. torch/diffusers are lazy ``[image]`` deps.

UNMEASURED FAMILY: pose-lock, IP-Adapter, and inpaint stay refused here. SDXL is the
implemented encoder. ``generate()`` still refuses rather than silently accepting
conditioning it cannot apply."""

from __future__ import annotations

from pathlib import Path

from ....core.loop.generator_iface import GenerationResult
from ....errors import PromptCraftError
from . import conditioning as cond
from ._device import select_device, select_dtype


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
            import torch  # noqa: F401
            from diffusers import FluxPipeline  # type: ignore
        except Exception as err:
            raise PromptCraftError("DEP_IMAGE_MISSING", "Flux needs the [image] extra (torch + diffusers)") from err

        # F-10b380ba: FLUX.1-dev is a 12B-parameter model; the official usage snippet loads bf16
        # specifically because float32 roughly doubles the ~24GB bf16 footprint. prefer_bf16=True on
        # CUDA reflects that; CPU still gets float32 (bf16-on-CPU support varies by torch build).
        # F-02ff1a21: keep select_device/select_dtype inside the classified load try.
        device = "unset"
        try:
            device = select_device(torch)
            dtype = select_dtype(torch, device, prefer_bf16=True)
            pipe = FluxPipeline.from_pretrained(self.model_id, torch_dtype=dtype)
            self._pipe = pipe.to(device)
        except Exception as err:
            raise PromptCraftError(
                "RUNTIME_GENERATOR_LOAD_FAILED",
                f"Flux pipeline {self.model_id!r} failed to load/move to device {device!r}: {err}",
                cause=err,
            ) from err
        return self._pipe

    def generate(self, prompt: str, negative_prompt: str, conditioning: dict, seed: int) -> GenerationResult:
        # Unmeasured family: pose-lock / identity-bind / inpaint stay refused until a
        # Director-gated measurement says Flux may apply them. SDXL is the implemented encoder.
        cond.refuse_unmeasured_family(self.generator_id, self.family, conditioning)

        pipe = self._load()
        try:
            import torch  # type: ignore

            generator = torch.Generator(device=getattr(pipe, "device", "cpu")).manual_seed(seed)
            image = pipe(prompt=prompt, num_inference_steps=self.steps, generator=generator).images[0]
            self.out_dir.mkdir(parents=True, exist_ok=True)
            path = self.out_dir / f"{self.generator_id}_seed{seed}.png"
            image.save(path)
        except Exception as err:
            # F-2ef1bb79: convert a raw call-time failure into the one structured error type.
            raise PromptCraftError(
                "RUNTIME_GENERATE_FAILED",
                f"{self.generator_id} failed generating seed={seed}: {err}",
                cause=err,
            ) from err

        return GenerationResult(
            image_path=str(path), seed=seed, sampler="flow-match", generator_id=self.generator_id,
            generator_family=self.family, conditioning=conditioning,
        )
