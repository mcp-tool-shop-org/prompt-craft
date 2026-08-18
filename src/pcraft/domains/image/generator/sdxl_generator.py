"""SDXL generator: text + assembled conditioning -> pixels.

The contract NAMES the conditioning; this generator ASSEMBLES it:

- ``spatial.pose`` refs -> ControlNet OpenPose (``image=`` / ``control_image=``)
- ``identity_ref`` with ``method=ip_adapter`` -> IP-Adapter on the plate
- ``inpaint_from`` + ``inpaint_region`` -> SDXL inpaint with a region mask

``family = "stable-diffusion"`` -- it must differ from every gate verifier family.

A named ref that is not a readable file is refused BEFORE the pipeline loads
(``GATE_CONDITIONING_REF_MISSING``). ``method=lora`` / ``instantid`` are still
refused (unimplemented). Flux is a different file and stays refused until measured.

torch/diffusers/PIL are optional ``[image]`` deps, imported lazily so importing
this module stays GPU-free. No generate() call here downloads or spends.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ....core.loop.generator_iface import GenerationResult
from ....errors import PromptCraftError
from . import conditioning as cond
from ._device import select_device, select_dtype

_LOG = logging.getLogger(__name__)

# F-4409b547: nothing in this file ever configures the pipeline's scheduler to match a requested
# sampler (that requires constructing e.g. DPMSolverMultistepScheduler onto pipe.scheduler, a real
# diffusers pipeline change this pass cannot verify without installing diffusers). Every reported
# sampler carries this suffix so the receipt cannot be misread as "this algorithm produced the
# pixels" -- see the comment on GenerationResult.sampler below.
_SAMPLER_UNAPPLIED_NOTE = "requested, NOT applied -- pipeline scheduler left at checkpoint default"

_DEFAULT_CONTROLNET = "xinsir/controlnet-openpose-sdxl-1.0"
_DEFAULT_IP_ADAPTER_REPO = "h94/IP-Adapter"
_DEFAULT_IP_ADAPTER_SUBFOLDER = "sdxl_models"
_DEFAULT_IP_ADAPTER_WEIGHT = "ip-adapter_sdxl.bin"


class SDXLGenerator:
    generator_id = "sdxl.base-1.0.v1"
    family = "stable-diffusion"

    def __init__(
        self,
        model_id: str = "stabilityai/stable-diffusion-xl-base-1.0",
        out_dir: str | Path = "records/_image",
        steps: int = 30,
        sampler: str = "dpmpp_2m_karras",
        controlnet_id: str = _DEFAULT_CONTROLNET,
        ip_adapter_repo: str = _DEFAULT_IP_ADAPTER_REPO,
        ip_adapter_subfolder: str = _DEFAULT_IP_ADAPTER_SUBFOLDER,
        ip_adapter_weight: str = _DEFAULT_IP_ADAPTER_WEIGHT,
    ):
        self.model_id = model_id
        self.out_dir = Path(out_dir)
        self.steps = steps
        self.sampler = sampler  # the REQUEST; see _SAMPLER_UNAPPLIED_NOTE -- never wired to a scheduler
        self.controlnet_id = controlnet_id
        self.ip_adapter_repo = ip_adapter_repo
        self.ip_adapter_subfolder = ip_adapter_subfolder
        self.ip_adapter_weight = ip_adapter_weight
        self._pipe = None
        self._pipe_kind: str | None = None

    def _load(self, kind: str = "base"):
        if self._pipe is not None and self._pipe_kind == kind:
            return self._pipe
        try:
            import torch  # noqa: F401
            import diffusers  # noqa: F401
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
            pipe = self._build_pipe(kind, dtype)
            if "ip" in kind.split("_"):
                pipe.load_ip_adapter(
                    self.ip_adapter_repo,
                    subfolder=self.ip_adapter_subfolder,
                    weight_name=self.ip_adapter_weight,
                )
            self._pipe = pipe.to(device)
            self._pipe_kind = kind
        except PromptCraftError:
            raise
        except Exception as err:
            raise PromptCraftError(
                "RUNTIME_GENERATOR_LOAD_FAILED",
                f"SDXL pipeline {self.model_id!r} kind={kind!r} failed to load/move "
                f"to device {device!r}: {err}",
                cause=err,
            ) from err
        return self._pipe

    def _build_pipe(self, kind: str, dtype):
        wants_cn = "controlnet" in kind
        wants_inpaint = kind.startswith("inpaint")
        if wants_cn and wants_inpaint:
            from diffusers import ControlNetModel, StableDiffusionXLControlNetInpaintPipeline  # type: ignore

            controlnet = ControlNetModel.from_pretrained(self.controlnet_id, torch_dtype=dtype)
            return StableDiffusionXLControlNetInpaintPipeline.from_pretrained(
                self.model_id, controlnet=controlnet, torch_dtype=dtype
            )
        if wants_cn:
            from diffusers import ControlNetModel, StableDiffusionXLControlNetPipeline  # type: ignore

            controlnet = ControlNetModel.from_pretrained(self.controlnet_id, torch_dtype=dtype)
            return StableDiffusionXLControlNetPipeline.from_pretrained(
                self.model_id, controlnet=controlnet, torch_dtype=dtype
            )
        if wants_inpaint:
            from diffusers import StableDiffusionXLInpaintPipeline  # type: ignore

            return StableDiffusionXLInpaintPipeline.from_pretrained(self.model_id, torch_dtype=dtype)
        from diffusers import StableDiffusionXLPipeline  # type: ignore

        return StableDiffusionXLPipeline.from_pretrained(self.model_id, torch_dtype=dtype)

    def generate(self, prompt: str, negative_prompt: str, conditioning: dict, seed: int) -> GenerationResult:
        conditioning = cond.assert_refs_readable(conditioning, generator_id=self.generator_id)
        cond.refuse_unimplemented_identity(self.generator_id, conditioning)
        kind = cond.pipeline_kind(conditioning)
        pipe = self._load(kind)
        try:
            import torch  # type: ignore

            generator = torch.Generator(device=getattr(pipe, "device", "cpu")).manual_seed(seed)
            call = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "num_inference_steps": self.steps,
                "generator": generator,
            }
            applied: dict = {"kind": kind, "pose": [], "ip_adapter": [], "inpaint": None}

            poses = [cond.open_image(p) for p in cond.pose_paths(conditioning)]
            if poses:
                pose_arg = poses[0] if len(poses) == 1 else poses
                if kind.startswith("inpaint"):
                    call["control_image"] = pose_arg
                else:
                    call["image"] = pose_arg
                call["controlnet_conditioning_scale"] = 0.8
                applied["pose"] = cond.pose_paths(conditioning)

            plates = cond.ip_adapter_refs(conditioning)
            if plates:
                images = [cond.open_image(p["plate"]) for p in plates]
                scales = []
                bump = float(conditioning.get("identity_weight_bump") or 0.0)
                for plate in plates:
                    weight = float(plate.get("weight") or 0.6) + bump
                    scales.append(min(1.0, max(0.0, weight)))
                call["ip_adapter_image"] = images[0] if len(images) == 1 else images
                pipe.set_ip_adapter_scale(scales[0] if len(scales) == 1 else scales)
                applied["ip_adapter"] = [
                    {"plate": p["plate"], "scale": s} for p, s in zip(plates, scales, strict=True)
                ]

            src = cond.inpaint_from(conditioning)
            if src:
                init = cond.open_image(src)
                region = cond.inpaint_region(conditioning)
                size = getattr(init, "size", (64, 64))
                call["image"] = init
                call["mask_image"] = cond.mask_for_region(size, region)
                call["strength"] = 0.85
                applied["inpaint"] = {"from": src, "region": region}

            image = pipe(**call).images[0]
            self.out_dir.mkdir(parents=True, exist_ok=True)
            suffix = "_inpaint" if src else ""
            path = self.out_dir / f"{self.generator_id}_seed{seed}{suffix}.png"
            image.save(path)
        except PromptCraftError:
            raise
        except Exception as err:
            # F-2ef1bb79: a call-time failure (CUDA OOM, a shape mismatch, torch vanishing between
            # _load() and here) used to surface as a completely raw, unclassified exception. Convert
            # it into the one structured error type instead of letting it escape bare.
            raise PromptCraftError(
                "RUNTIME_GENERATE_FAILED",
                f"{self.generator_id} failed generating seed={seed}: {err}",
                cause=err,
            ) from err

        receipt_cond = {**conditioning, "applied": applied}
        return GenerationResult(
            image_path=str(path),
            seed=seed,
            sampler=f"{self.sampler} [{_SAMPLER_UNAPPLIED_NOTE}]",
            generator_id=self.generator_id,
            generator_family=self.family,
            conditioning=receipt_cond,
        )
