"""SDXL generator: text + assembled conditioning -> pixels.

The contract NAMES the conditioning; a full implementation of this generator would ASSEMBLE it:
``spatial.pose`` refs becoming ControlNet inputs (locking 'axe in both hands', foot-anchor,
engine-placeable scale), ``identity_ref`` becoming IP-Adapter / LoRA on the reference plate.
``family = "stable-diffusion"`` -- it must differ from every gate verifier family.

STAGE A HONESTY NOTE (F-657db549): that assembly is NOT implemented here. ``StableDiffusionXLPipeline``
is the plain base txt2img pipeline -- no ControlNet, no IP-Adapter, no reference-plate conditioning of
any kind. Implementing that is feature-pass GPU work, out of scope for this pass. What this pass does
instead is make the gap loud: if the caller asks for ``pose_refs`` or ``identity_refs`` that this
generator cannot apply, ``generate()`` refuses with a classified error rather than silently accepting
the dict, doing a plain text-to-image render, and echoing the ignored conditioning back onto the
receipt as if it meant something.

torch/diffusers are an optional ``[image]`` dependency, imported lazily inside ``generate`` so that
importing this module (and the whole plugin) stays GPU-free."""

from __future__ import annotations

import logging
from pathlib import Path

from ....errors import PromptCraftError
from ....core.loop.generator_iface import GenerationResult
from ._device import select_device, select_dtype

_LOG = logging.getLogger(__name__)

# F-4409b547: nothing in this file ever configures the pipeline's scheduler to match a requested
# sampler (that requires constructing e.g. DPMSolverMultistepScheduler onto pipe.scheduler, a real
# diffusers pipeline change this pass cannot verify without installing diffusers). Every reported
# sampler carries this suffix so the receipt cannot be misread as "this algorithm produced the
# pixels" -- see the comment on GenerationResult.sampler below.
_SAMPLER_UNAPPLIED_NOTE = "requested, NOT applied -- pipeline scheduler left at checkpoint default"


class SDXLGenerator:
    generator_id = "sdxl.base-1.0.v1"
    family = "stable-diffusion"

    def __init__(
        self,
        model_id: str = "stabilityai/stable-diffusion-xl-base-1.0",
        out_dir: str | Path = "records/_image",
        steps: int = 30,
        sampler: str = "dpmpp_2m_karras",
    ):
        self.model_id = model_id
        self.out_dir = Path(out_dir)
        self.steps = steps
        self.sampler = sampler  # the REQUEST; see _SAMPLER_UNAPPLIED_NOTE -- never wired to a scheduler
        self._pipe = None

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        try:
            import torch  # noqa: F401
            from diffusers import StableDiffusionXLPipeline  # type: ignore
        except Exception as err:
            raise PromptCraftError("DEP_IMAGE_MISSING", "SDXL needs the [image] extra (torch + diffusers)") from err

        # F-10b380ba: previously neither device nor dtype were selected, so the pipeline loaded to
        # CPU in float32 by default (documented diffusers behaviour) with nothing logging that fact.
        # F-02ff1a21: select_device/select_dtype used to sit between the two try blocks, so a
        # surprise from the torch stand-in escaped unclassified.
        device = "unset"
        try:
            device = select_device(torch)
            dtype = select_dtype(torch, device)
            pipe = StableDiffusionXLPipeline.from_pretrained(self.model_id, torch_dtype=dtype)
            self._pipe = pipe.to(device)
        except Exception as err:
            raise PromptCraftError(
                "RUNTIME_GENERATOR_LOAD_FAILED",
                f"SDXL pipeline {self.model_id!r} failed to load/move to device {device!r}: {err}",
                cause=err,
            ) from err
        return self._pipe

    def generate(self, prompt: str, negative_prompt: str, conditioning: dict, seed: int) -> GenerationResult:
        # F-657db549: refuse rather than silently no-op. pose_refs -> ControlNet(openpose) pose-lock
        # and identity_refs -> IP-Adapter/LoRA identity binding are the contract's own documented
        # capability (core/contract/schema.py's Spatial docstring); this generator does not implement
        # either. Forwarding the dict into the receipt unread would look like the render honoured a
        # promise it never kept. A caller that never asks for pose/identity conditioning (the common
        # case for a plain prompt-only render) is unaffected -- this only fires on a real mismatch
        # between what the contract asked for and what this generator can do.
        if conditioning.get("pose_refs") or conditioning.get("identity_refs"):
            raise PromptCraftError(
                "GATE_CONDITIONING_UNSUPPORTED",
                f"{self.generator_id} cannot apply pose_refs/identity_refs conditioning: "
                "ControlNet(openpose) pose-lock and IP-Adapter identity binding are not implemented "
                "by this generator (plain StableDiffusionXLPipeline txt2img only)",
                hint="Drop pose_refs/identity_refs from the contract for this generator, or use/build "
                "a generator that actually assembles them (StableDiffusionXLControlNetPipeline / "
                ".load_ip_adapter()) before relying on pose-lock or identity binding.",
            )

        pipe = self._load()
        try:
            import torch  # type: ignore

            generator = torch.Generator(device=getattr(pipe, "device", "cpu")).manual_seed(seed)
            image = pipe(
                prompt=prompt, negative_prompt=negative_prompt, num_inference_steps=self.steps, generator=generator
            ).images[0]
            self.out_dir.mkdir(parents=True, exist_ok=True)
            path = self.out_dir / f"{self.generator_id}_seed{seed}.png"
            image.save(path)
        except Exception as err:
            # F-2ef1bb79: a call-time failure (CUDA OOM, a shape mismatch, torch vanishing between
            # _load() and here) used to surface as a completely raw, unclassified exception. Convert
            # it into the one structured error type instead of letting it escape bare.
            raise PromptCraftError(
                "RUNTIME_GENERATE_FAILED",
                f"{self.generator_id} failed generating seed={seed}: {err}",
                cause=err,
            ) from err

        return GenerationResult(
            image_path=str(path),
            seed=seed,
            sampler=f"{self.sampler} [{_SAMPLER_UNAPPLIED_NOTE}]",
            generator_id=self.generator_id,
            generator_family=self.family,
            conditioning=conditioning,
        )
