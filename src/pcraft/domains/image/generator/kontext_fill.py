"""Cloud recipe: Kontext stitch + in-graph left crop + fist-only Flux Fill.

Measured 2026-08-18 on ashen-reaver (Cloud OSS, graph
https://cloud.comfy.org/#a3c8c6af-41a1-45f6-b8ca-dab171d9bcc0):

1. Flux.1 Kontext Dev. ImageStitch identity (left) + OpenPose (right).
2. Crop the LEFT panel in-graph so Kontext does not ship a diptych.
3. Flux.1 Fill Dev. Mask only the fist. Do not mask the bracer.

``method=reference`` is this path. SDXL does not run it. This module is
GPU-free: it builds the API graph. It does not submit and does not spend.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ....errors import PromptCraftError
from . import conditioning as cond
from .reference_lock import ReferenceLock, assemble, as_generate_refs

RECIPE_ID = "flux.kontext-stitch-crop-fill.v1"
MEASURED_GRAPH = "https://cloud.comfy.org/#a3c8c6af-41a1-45f6-b8ca-dab171d9bcc0"

KONTEXT_UNET = "flux1-dev-kontext_fp8_scaled.safetensors"
FILL_UNET = "flux1-fill-dev.safetensors"
CLIP_L = "clip_l.safetensors"
T5 = "t5xxl_fp8_e4m3fn_scaled.safetensors"
VAE_NAME = "ae.safetensors"

# Viewer's-right fist on the cropped ashen-reaver sheet. The bone-spike
# bracer sits above this box; a hands/weapon region ate it.
FIST_X0 = 0.62
FIST_Y0 = 0.48
FIST_X1 = 0.88
FIST_Y1 = 0.65
FIST_W = 0.26
FIST_H = 0.17

BRACER_REGIONS = frozenset({"hands", "hand", "weapon"})

DEFAULT_KONTEXT_PROMPT = (
    "The orc warrior from the left image, in the two-hand axe grip of the "
    "pose map on the right. Keep the same face, tusks, grey-green skin, "
    "ash-grey tabard, white hashed triple-bar sigil, blood-red sash, and "
    "painted character-sheet style."
)
DEFAULT_FILL_PROMPT = (
    "The fist wraps the wooden axe shaft. Wood in the palm. Do not change "
    "the bone-spike bracer, the face, or the hashed triple-bar sigil."
)

STAGES = ("stitch", "kontext", "crop_left", "fill_fist")


class RecipeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe_id: str = RECIPE_ID
    stages: list[str] = list(STAGES)
    identity: str
    pose: str
    crop: str = "left-half"
    fill_region: str = "fist"
    do_not_mask_bracer: bool = True
    kontext_prompt: str
    fill_prompt: str
    seed: int
    measured_graph: str = MEASURED_GRAPH
    graph_path: str = ""


class _Graph:
    def __init__(self) -> None:
        self._n = 0
        self.nodes: dict[str, dict] = {}
        self.ids: dict[str, str] = {}

    def add(self, key: str, class_type: str, **inputs) -> str:
        self._n += 1
        nid = str(self._n)
        self.ids[key] = nid
        self.nodes[nid] = {"class_type": class_type, "inputs": inputs}
        return nid

    def link(self, key: str, slot: int = 0) -> list:
        return [self.ids[key], slot]


def _math(graph: _Graph, key: str, expression: str, **values) -> str:
    """ComfyMathExpression: FLOAT / INT / BOOLEAN. Use slot 1 for the INT."""
    return graph.add(key, "ComfyMathExpression", expression=expression, values=values)


def build_graph(
    lock: ReferenceLock,
    *,
    kontext_prompt: str = DEFAULT_KONTEXT_PROMPT,
    fill_prompt: str = DEFAULT_FILL_PROMPT,
    fill_region: str = "fist",
    fill_mask: str | Path | None = None,
    seed: int = 169405236028824,
) -> dict:
    """API-format Comfy graph (node-id keys, class_type + inputs)."""
    refs = as_generate_refs(lock)
    if not lock.identity:
        raise PromptCraftError(
            "GATE_CONDITIONING_REF_MISSING",
            "the Kontext stitch needs an identity plate",
            hint="Bind identity_ref. method=reference is this Cloud recipe.",
        )
    if not lock.pose:
        raise PromptCraftError(
            "GATE_CONDITIONING_REF_MISSING",
            "the Kontext stitch needs a pose map",
            hint="A spatial.kind=pose atom names the OpenPose plate.",
        )
    region = (fill_region or "fist").strip().lower()
    if fill_mask is None and region in BRACER_REGIONS:
        raise PromptCraftError(
            "GATE_CONDITIONING_UNSUPPORTED",
            f"fill region {region!r} masks the bracer; the keeper used fist-only",
            hint="Use fill_region=fist, or pass a painted fist-only mask. "
            "Do not mask the bracer.",
        )
    if fill_mask is None and region != "fist":
        raise PromptCraftError(
            "GATE_CONDITIONING_UNSUPPORTED",
            f"fill region {region!r} is not the measured fist-only mask",
            hint="The Fill pass is fist-only. Use fill_region=fist.",
        )

    identity = str(refs[0])
    pose = lock.pose[0]
    graph = _Graph()

    graph.add("identity", "LoadImage", image=Path(identity).name)
    graph.add("pose", "LoadImage", image=Path(pose).name)
    graph.add(
        "stitch",
        "ImageStitch",
        image1=graph.link("identity"),
        image2=graph.link("pose"),
        direction="right",
        match_image_size=True,
        spacing_width=0,
        spacing_color="white",
    )

    graph.add("kontext_unet", "UNETLoader", unet_name=KONTEXT_UNET, weight_dtype="default")
    graph.add("fill_unet", "UNETLoader", unet_name=FILL_UNET, weight_dtype="default")
    graph.add(
        "clip",
        "DualCLIPLoader",
        clip_name1=CLIP_L,
        clip_name2=T5,
        type="flux",
        device="default",
    )
    graph.add("vae", "VAELoader", vae_name=VAE_NAME)

    graph.add("scale", "FluxKontextImageScale", image=graph.link("stitch"))
    graph.add("kontext_pixels", "VAEEncode", pixels=graph.link("scale"), vae=graph.link("vae"))
    graph.add("kontext_pos", "CLIPTextEncode", clip=graph.link("clip"), text=kontext_prompt)
    graph.add(
        "ref_latent",
        "ReferenceLatent",
        conditioning=graph.link("kontext_pos"),
        latent=graph.link("kontext_pixels"),
    )
    graph.add("kontext_guid", "FluxGuidance", conditioning=graph.link("ref_latent"), guidance=2.5)
    graph.add("kontext_zero", "ConditioningZeroOut", conditioning=graph.link("kontext_pos"))
    graph.add(
        "kontext_sample",
        "KSampler",
        model=graph.link("kontext_unet"),
        positive=graph.link("kontext_guid"),
        negative=graph.link("kontext_zero"),
        latent_image=graph.link("kontext_pixels"),
        seed=seed,
        control_after_generate="fixed",
        steps=20,
        cfg=1.0,
        sampler_name="euler",
        scheduler="simple",
        denoise=1.0,
    )
    graph.add("kontext_out", "VAEDecode", samples=graph.link("kontext_sample"), vae=graph.link("vae"))

    # Left panel of the diptych. Size comes from the Kontext output, not a guess.
    graph.add("diptych_size", "GetImageSize", image=graph.link("kontext_out"))
    _math(graph, "half_w", "a / 2", a=graph.link("diptych_size", 0))
    graph.add(
        "left_box",
        "PrimitiveBoundingBox",
        x=0,
        y=0,
        width=graph.link("half_w", 1),
        height=graph.link("diptych_size", 1),
    )
    graph.add(
        "crop",
        "ImageCropV2",
        image=graph.link("kontext_out"),
        crop_region=graph.link("left_box"),
    )

    graph.add("crop_size", "GetImageSize", image=graph.link("crop"))
    if fill_mask is not None:
        graph.add("mask_img", "LoadImage", image=Path(fill_mask).name)
        graph.add("fist_mask", "ImageToMask", image=graph.link("mask_img"), channel="red")
    else:
        _math(graph, "fist_x", f"a * {FIST_X0}", a=graph.link("crop_size", 0))
        _math(graph, "fist_y", f"a * {FIST_Y0}", a=graph.link("crop_size", 1))
        _math(graph, "fist_w", f"a * {FIST_W}", a=graph.link("crop_size", 0))
        _math(graph, "fist_h", f"a * {FIST_H}", a=graph.link("crop_size", 1))
        graph.add(
            "empty_mask",
            "SolidMask",
            value=0.0,
            width=graph.link("crop_size", 0),
            height=graph.link("crop_size", 1),
        )
        graph.add(
            "fist_blob",
            "SolidMask",
            value=1.0,
            width=graph.link("fist_w", 1),
            height=graph.link("fist_h", 1),
        )
        graph.add(
            "fist_placed",
            "MaskComposite",
            destination=graph.link("empty_mask"),
            source=graph.link("fist_blob"),
            x=graph.link("fist_x", 1),
            y=graph.link("fist_y", 1),
            operation="add",
        )
        graph.add(
            "fist_mask",
            "FeatherMask",
            mask=graph.link("fist_placed"),
            left=8,
            top=8,
            right=8,
            bottom=8,
        )

    graph.add("fill_pos", "CLIPTextEncode", clip=graph.link("clip"), text=fill_prompt)
    graph.add("fill_neg", "ConditioningZeroOut", conditioning=graph.link("fill_pos"))
    graph.add(
        "fill_cond",
        "InpaintModelConditioning",
        positive=graph.link("fill_pos"),
        negative=graph.link("fill_neg"),
        vae=graph.link("vae"),
        pixels=graph.link("crop"),
        mask=graph.link("fist_mask"),
        noise_mask=True,
    )
    graph.add("fill_guid", "FluxGuidance", conditioning=graph.link("fill_cond"), guidance=30.0)
    graph.add(
        "fill_sample",
        "KSampler",
        model=graph.link("fill_unet"),
        positive=graph.link("fill_guid"),
        negative=graph.link("fill_cond", 1),
        latent_image=graph.link("fill_cond", 2),
        seed=seed,
        control_after_generate="fixed",
        steps=20,
        cfg=1.0,
        sampler_name="euler",
        scheduler="simple",
        denoise=1.0,
    )
    graph.add("fill_out", "VAEDecode", samples=graph.link("fill_sample"), vae=graph.link("vae"))
    graph.add("save", "SaveImage", images=graph.link("fill_out"), filename_prefix=RECIPE_ID)
    return graph.nodes


def report_for(
    lock: ReferenceLock,
    *,
    kontext_prompt: str = DEFAULT_KONTEXT_PROMPT,
    fill_prompt: str = DEFAULT_FILL_PROMPT,
    fill_region: str = "fist",
    seed: int = 169405236028824,
    graph_path: str = "",
) -> RecipeReport:
    return RecipeReport(
        identity=lock.identity[0] if lock.identity else "",
        pose=lock.pose[0] if lock.pose else "",
        fill_region=fill_region,
        kontext_prompt=kontext_prompt,
        fill_prompt=fill_prompt,
        seed=seed,
        graph_path=graph_path,
    )


def from_conditioning(
    conditioning: dict,
    *,
    kontext_prompt: str = DEFAULT_KONTEXT_PROMPT,
    fill_prompt: str = DEFAULT_FILL_PROMPT,
    fill_region: str = "fist",
    fill_mask: str | Path | None = None,
    seed: int = 169405236028824,
) -> tuple[dict, RecipeReport]:
    bound = cond.bind_refs(conditioning, generator_id="flux.kontext-fill.v1")
    lock = assemble(bound)
    graph = build_graph(
        lock,
        kontext_prompt=kontext_prompt,
        fill_prompt=fill_prompt,
        fill_region=fill_region,
        fill_mask=fill_mask,
        seed=seed,
    )
    return graph, report_for(
        lock,
        kontext_prompt=kontext_prompt,
        fill_prompt=fill_prompt,
        fill_region=fill_region,
        seed=seed,
    )
