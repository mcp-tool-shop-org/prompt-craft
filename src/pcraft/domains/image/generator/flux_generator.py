"""Flux generator (swappable encoder per the system-architecture reuse slot).

Same plugin contract as SDXL; ``family = "flux"``.

What this encoder applies:

- text-only ``FluxPipeline`` (FLUX.1-dev)
- regional inpaint via ``FluxFillPipeline`` (FLUX.1-Fill-dev)
- ``method=reference`` writes the Cloud Kontext + fist-only Fill graph
  (does not run Kontext locally)

What it refuses: ControlNet pose, IP-Adapter, LoRA, InstantID. Those are
the SDXL family. torch/diffusers are lazy ``[image]`` deps."""

from __future__ import annotations

from pathlib import Path

from ....core.loop.generator_iface import GenerationResult
from ....errors import PromptCraftError
from . import conditioning as cond
from ._device import select_device, select_dtype


class FluxGenerator:
    generator_id = "flux.1-dev.v1"
    family = "flux"

    def __init__(
        self,
        model_id: str = "black-forest-labs/FLUX.1-dev",
        fill_model_id: str = "black-forest-labs/FLUX.1-Fill-dev",
        out_dir: str | Path = "records/_image",
        steps: int = 28,
    ):
        self.model_id = model_id
        self.fill_model_id = fill_model_id
        self.out_dir = Path(out_dir)
        self.steps = steps
        self._pipe = None
        self._pipe_kind: str | None = None

    def _load(self, kind: str = "base"):
        if self._pipe is not None and self._pipe_kind == kind:
            return self._pipe
        try:
            import diffusers  # noqa: F401
            import torch
        except Exception as err:
            raise PromptCraftError(
                "DEP_IMAGE_MISSING", "Flux needs the [image] extra (torch + diffusers)"
            ) from err

        device = "unset"
        try:
            device = select_device(torch)
            dtype = select_dtype(torch, device, prefer_bf16=True)
            if kind == "inpaint":
                from diffusers import FluxFillPipeline  # type: ignore

                pipe = FluxFillPipeline.from_pretrained(self.fill_model_id, torch_dtype=dtype)
            else:
                from diffusers import FluxPipeline  # type: ignore

                pipe = FluxPipeline.from_pretrained(self.model_id, torch_dtype=dtype)
            self._pipe = pipe.to(device)
            self._pipe_kind = kind
        except PromptCraftError:
            raise
        except Exception as err:
            raise PromptCraftError(
                "RUNTIME_GENERATOR_LOAD_FAILED",
                f"Flux pipeline failed to load/move to device {device!r}: {err}",
                cause=err,
            ) from err
        return self._pipe

    def _write_reference_recipe(self, conditioning: dict) -> Path:
        from . import kontext_fill
        from .reference_lock import assemble

        bound = cond.bind_refs(conditioning, generator_id=self.generator_id)
        lock = assemble(bound)
        graph = kontext_fill.build_graph(lock)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{kontext_fill.RECIPE_ID}.json"
        import json

        path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        return path

    def generate(self, prompt: str, negative_prompt: str, conditioning: dict, seed: int) -> GenerationResult:
        conditioning = cond.assert_refs_readable(conditioning, generator_id=self.generator_id)
        cond.refuse_unimplemented_identity(self.generator_id, conditioning)
        # F-43da2300 (ordering): a wrong-family identity lock is refused BEFORE the reference branch
        # can write a recipe. Testing reference_refs first meant a conditioning carrying both a
        # reference ref and an ip_adapter/lora/instantid ref emitted a Cloud graph and raised
        # GATE_CLOUD_SUBMIT with the wrong-family lock never refused at all. The pose half of
        # refuse_unmeasured_family stays BELOW: on the reference path the pose map is the recipe's
        # own ImageStitch input, not an SDXL ControlNet request.
        cond.refuse_unmeasured_identity_family(self.generator_id, self.family, conditioning)
        if cond.reference_refs(conditioning):
            path = self._write_reference_recipe(conditioning)
            raise PromptCraftError(
                "GATE_CLOUD_SUBMIT",
                f"{self.generator_id} wrote the Cloud recipe to {path}; "
                "it does not run Kontext locally",
                hint="Submit that graph on Comfy Cloud (pcraft recipe --image-name …). "
                "Do not treat this refuse as a missing plate.",
            )
        cond.refuse_unmeasured_family(self.generator_id, self.family, conditioning)

        kind = "inpaint" if cond.inpaint_from(conditioning) else "base"
        pipe = self._load(kind)
        try:
            import torch  # type: ignore

            generator = torch.Generator(device=getattr(pipe, "device", "cpu")).manual_seed(seed)
            # F-cd07fe00: negative_prompt is accepted and then DROPPED. Dropping it is correct for
            # the model -- rules/encoder_craft.md:843, FLUX-dev/schnell are guidance-distilled and
            # ignore negatives, so every token there is dead weight. What was wrong was the silence:
            # core/synth/signature.py builds the negative by joining every must_not claim and the
            # CLI prints it, so the operator saw a suppression the pipeline never received. Record
            # the drop the way sdxl_generator records its unapplied sampler.
            # The FluxFillPipeline branch drops it too: wiring that pipeline's negative_prompt /
            # true_cfg_scale is a real diffusers change this pass cannot verify (diffusers is not
            # installed here), so the choice made is "still dropped, and stamped as dropped".
            call = {"prompt": prompt, "num_inference_steps": self.steps, "generator": generator}
            applied: dict = {
                "kind": kind,
                "inpaint": None,
                "negative_prompt": (
                    {
                        "requested": negative_prompt,
                        "applied": False,
                        "reason": "FLUX.1-dev is guidance-distilled; negative_prompt is inert "
                        "without a true-CFG pass, so it is not passed to the pipeline",
                    }
                    if negative_prompt
                    else None
                ),
            }
            src = cond.inpaint_from(conditioning)
            if src:
                init = cond.open_image(src)
                region = cond.inpaint_region(conditioning)
                size = getattr(init, "size", (64, 64))
                call["image"] = init
                call["mask_image"] = cond.mask_for_region(size, region)
                applied["inpaint"] = {"from": src, "region": region}
            image = pipe(**call).images[0]
            self.out_dir.mkdir(parents=True, exist_ok=True)
            suffix = "_inpaint" if src else ""
            path = self.out_dir / f"{self.generator_id}_seed{seed}{suffix}.png"
            image.save(path)
        except PromptCraftError:
            raise
        except Exception as err:
            raise PromptCraftError(
                "RUNTIME_GENERATE_FAILED",
                f"{self.generator_id} failed generating seed={seed}: {err}",
                cause=err,
            ) from err

        return GenerationResult(
            image_path=str(path),
            seed=seed,
            # Nothing in this file configures a scheduler, so "flow-match" is what the checkpoint
            # shipped with, not an algorithm anyone chose. Say so (F-cd07fe00), the way
            # sdxl_generator says so for its requested-but-unapplied sampler.
            sampler="flow-match [pipeline default]",
            generator_id=self.generator_id,
            generator_family=self.family,
            conditioning={**conditioning, "applied": applied},
        )
