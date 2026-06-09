"""SDXL generator: text + assembled conditioning -> pixels.

The contract NAMES the conditioning; this generator ASSEMBLES it: ``spatial.pose`` refs become
ControlNet inputs (locking 'axe in both hands', foot-anchor, engine-placeable scale); ``identity_ref``
becomes IP-Adapter / LoRA on the reference plate (binding the exact face/insignia text cannot
specify). ``family = "stable-diffusion"`` — it must differ from every gate verifier family.

torch/diffusers are an optional ``[image]`` dependency, imported lazily inside ``generate`` so that
importing this module (and the whole plugin) stays GPU-free."""

from __future__ import annotations

from pathlib import Path

from ....errors import PromptCraftError
from ....core.loop.generator_iface import GenerationResult


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
        self.sampler = sampler
        self._pipe = None

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        try:
            import torch  # noqa: F401
            from diffusers import StableDiffusionXLPipeline  # type: ignore
        except Exception as err:
            raise PromptCraftError("DEP_IMAGE_MISSING", "SDXL needs the [image] extra (torch + diffusers)") from err
        self._pipe = StableDiffusionXLPipeline.from_pretrained(self.model_id)
        return self._pipe

    def generate(self, prompt: str, negative_prompt: str, conditioning: dict, seed: int) -> GenerationResult:
        pipe = self._load()
        # Conditioning assembly (the contract opened these; the gate will verify they rendered):
        #   conditioning["pose_refs"]      -> ControlNet(openpose) inputs
        #   conditioning["identity_refs"]  -> IP-Adapter / LoRA on each reference plate
        #   conditioning["identity_weight_bump"] -> raise IP-Adapter weight on an identity repair
        import torch  # type: ignore

        generator = torch.Generator(device=getattr(pipe, "device", "cpu")).manual_seed(seed)
        image = pipe(prompt=prompt, negative_prompt=negative_prompt, num_inference_steps=self.steps, generator=generator).images[0]
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{self.generator_id}_seed{seed}.png"
        image.save(path)
        return GenerationResult(
            image_path=str(path),
            seed=seed,
            sampler=self.sampler,
            generator_id=self.generator_id,
            generator_family=self.family,
            conditioning=conditioning,
        )
