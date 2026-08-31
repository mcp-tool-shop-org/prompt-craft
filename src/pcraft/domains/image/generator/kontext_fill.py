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

from pydantic import BaseModel, ConfigDict, Field

from ....errors import PromptCraftError
from . import conditioning as cond
from .reference_lock import ReferenceLock, assemble

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


BUILTIN_FIST_MASK = "builtin-fist"
SUPPLIED_MASK = "supplied-mask"


class MaskPlan(BaseModel):
    """What the Fill pass will ACTUALLY mask -- computed once, then both built and reported.

    F-90667b30: ``RecipeReport.do_not_mask_bracer`` used to be a hardcoded ``= True`` that nothing
    ever assigned, while ``build_graph``'s bracer guard was bypassed entirely whenever a painted
    ``fill_mask`` was supplied (both refusals are gated on ``fill_mask is None``). So
    ``fill_region='hands'`` plus any mask was accepted AND stamped as bracer-safe. The receipt may
    not assert a constraint nothing checked: this type is the one place the answer is computed, and
    ``build_graph`` and ``report_for`` both read it.
    """

    model_config = ConfigDict(extra="forbid")
    source: str  # BUILTIN_FIST_MASK | SUPPLIED_MASK
    region: str  # what the graph masks, NOT what was asked for
    requested_region: str
    # True only for the measured fist-only box. None = UNVERIFIED: a caller-painted mask's coverage
    # is not inspectable from here, so neither "spared" nor "eaten" is a claim this code can make.
    do_not_mask_bracer: bool | None


def _resolved_mask(fill_mask: str | Path) -> Path:
    """Existence-check a painted mask the way every other ref in this domain is checked.

    F-b8ee4b0a: passing ANY ``fill_mask`` value disabled BOTH bracer refusals -- they branch on
    ``fill_mask is None`` alone -- and nothing checked that the value named a readable file.
    ``conditioning.resolve_ref``, whose stated promise is to refuse "before any pipeline load if a
    ref cannot be opened", was applied to every identity plate, pose map and inpaint source, and to
    this one input it was not. So a typo in ``--fill-mask`` silently switched off the module's single
    measured safety constraint and exited 0 with a graph on disk: an unresolvable ``LoadImage``
    bound for Comfy Cloud at real spend, on the Fill pass whose documented failure mode is
    destroying the bone-spike bracer. A directory passed identically, and so did ``Path('')`` --
    what typer hands this layer for ``--fill-mask ""``.

    INPUT_ rather than GATE_: a mistyped path is bad user input (exit 1, "fix your input"), not a
    gate-discipline violation. The check lives here, in the one place the mask question is answered,
    so ``build_graph``, ``report_for`` and ``from_conditioning`` cannot disagree about it.
    """
    try:
        return cond.resolve_ref(fill_mask)
    except FileNotFoundError as err:
        raise PromptCraftError(
            "INPUT_FILL_MASK",
            f"fill mask {str(fill_mask)!r} is not a readable file",
            hint="Pass --fill-mask at a painted fist-only mask that exists. Supplying a mask "
            "replaces the built-in fist box AND turns the bracer guard off, so a mistyped path "
            "would disable the one constraint this recipe measures. Do not mask the bracer.",
            cause=err,
        ) from err


def resolve_mask_plan(fill_region: str = "fist", fill_mask: str | Path | None = None) -> MaskPlan:
    """Refuse the measured-unsafe regions, then say what the Fill pass will actually mask."""
    requested = (fill_region or "fist").strip().lower()
    if fill_mask is not None:
        # Refuse an unreadable mask BEFORE it is allowed to switch off the bracer refusals below.
        _resolved_mask(fill_mask)
    if fill_mask is None:
        if requested in BRACER_REGIONS:
            raise PromptCraftError(
                "GATE_CONDITIONING_UNSUPPORTED",
                f"fill region {requested!r} masks the bracer; the keeper used fist-only",
                hint="Use fill_region=fist, or pass a painted fist-only mask. "
                "Do not mask the bracer.",
            )
        if requested != "fist":
            raise PromptCraftError(
                "GATE_CONDITIONING_UNSUPPORTED",
                f"fill region {requested!r} is not the measured fist-only mask",
                hint="The Fill pass is fist-only. Use fill_region=fist.",
            )
        return MaskPlan(
            source=BUILTIN_FIST_MASK,
            region="fist",
            requested_region=requested,
            do_not_mask_bracer=True,
        )
    # A painted mask replaces the region box outright -- the region string is unused in graph
    # construction from here on, so the receipt must stop repeating it as if it were applied.
    return MaskPlan(
        source=SUPPLIED_MASK,
        region=SUPPLIED_MASK,
        requested_region=requested,
        do_not_mask_bracer=None,
    )


class RecipeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe_id: str = RECIPE_ID
    stages: list[str] = list(STAGES)
    identity: str
    identity_method: str = ""  # the method the contract DECLARED for the stitched plate
    # F-0e41e735: every plate that reaches the identity bucket now declares a method this recipe can
    # apply, so a second one is a legitimate composition rather than a wrong-family lock -- but the
    # stitch still takes exactly one. Name the rest. A silent first-wins on the identity lock is the
    # one outcome this module's docstrings say must not happen.
    identity_unchosen: list[str] = Field(default_factory=list)
    pose: str
    crop: str = "left-half"
    fill_region: str = "fist"  # what the Fill pass masks, not what was requested
    requested_fill_region: str = "fist"
    mask_source: str = BUILTIN_FIST_MASK
    do_not_mask_bracer: bool | None = True  # None = unverified (caller-painted mask)
    kontext_prompt: str
    fill_prompt: str
    seed: int
    measured_graph: str = MEASURED_GRAPH
    graph_path: str = ""
    cloud_names: dict[str, str] = Field(default_factory=dict)


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
    """ComfyMathExpression: FLOAT / INT / BOOLEAN. Use slot 1 for the INT.

    Cloud validates autogrow slots as dotted keys (``values.a``), not a nested
    ``values`` map. Dry-run accepted the nested form; a live submit 400'd.
    """
    inputs: dict = {"expression": expression}
    for name, val in values.items():
        inputs[f"values.{name}"] = val
    return graph.add(key, "ComfyMathExpression", **inputs)


def bind_cloud_names(graph: dict, names: dict[str, str]) -> dict:
    """Rewrite LoadImage filenames to Cloud upload names. Missing keys stay."""
    out = {}
    for nid, node in graph.items():
        copied = {"class_type": node["class_type"], "inputs": dict(node.get("inputs") or {})}
        if copied["class_type"] == "LoadImage":
            current = copied["inputs"].get("image")
            if current in names:
                copied["inputs"]["image"] = names[current]
        out[nid] = copied
    return out


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
    # One computation of what gets masked, shared with report_for() so the receipt cannot drift
    # from the graph (F-90667b30).
    resolve_mask_plan(fill_region, fill_mask)

    # F-0e41e735: read the identity bucket directly. This used to be ``as_generate_refs(lock)[0]``,
    # which happens to be the same plate but says "whatever sorted first" rather than "the identity
    # lock" -- and that indirection is precisely how a costume/pose ordering change could have
    # silently re-pointed the stitch.
    identity = str(lock.identity[0])
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
    fill_mask: str | Path | None = None,
    seed: int = 169405236028824,
    graph_path: str = "",
) -> RecipeReport:
    """Report what the graph WILL do. ``fill_mask`` is required to answer the bracer question."""
    plan = resolve_mask_plan(fill_region, fill_mask)
    identity = lock.identity[0] if lock.identity else ""
    return RecipeReport(
        identity=identity,
        identity_method=lock.method_for(identity),
        identity_unchosen=list(lock.identity[1:]),
        pose=lock.pose[0] if lock.pose else "",
        fill_region=plan.region,
        requested_fill_region=plan.requested_region,
        mask_source=plan.source,
        do_not_mask_bracer=plan.do_not_mask_bracer,
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
        fill_mask=fill_mask,
        seed=seed,
    )
