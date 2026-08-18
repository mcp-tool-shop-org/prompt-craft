"""Conditioning assembly for the image generators.

The contract names the lock (``spatial.kind=pose`` / ``identity_ref``). This module
resolves those names to readable files and refuses before any pipeline load if a
ref cannot be opened. Flux still refuses the whole family (unmeasured). SDXL
applies ControlNet(openpose) and IP-Adapter only.

GPU-free on purpose: path checks and region boxes use the stdlib. PIL is lazy
and only imported when an image actually has to be opened.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ....errors import PromptCraftError

# Packaged sprite tree (poses/ + plates/). Do not import the sprite package —
# that pulls identity_subgate. Path-only on purpose.
_SPRITE_ROOT = Path(__file__).resolve().parents[1] / "subdomains" / "sprite"

_IP_ADAPTER = "ip_adapter"
_REFERENCE = "reference"
_SKIP_METHODS = frozenset({"none"})
_UNIMPLEMENTED_METHODS: frozenset[str] = frozenset()
# hands/weapon ate the bone-spike bracer on the keeper Fill. fist is the measured box.
_FIST = (0.62, 0.48, 0.88, 0.65)


def pose_paths(conditioning: dict) -> list[str]:
    refs = conditioning.get("pose_refs") or []
    return [str(r) for r in refs if r]


def identity_refs(conditioning: dict) -> list[dict[str, Any]]:
    refs = conditioning.get("identity_refs") or []
    out: list[dict[str, Any]] = []
    for raw in refs:
        if not isinstance(raw, dict):
            continue
        method = str(raw.get("method") or _IP_ADAPTER)
        if method in _SKIP_METHODS:
            continue
        if raw.get("plate"):
            out.append({**raw, "method": method})
    return out


def ip_adapter_refs(conditioning: dict) -> list[dict[str, Any]]:
    return [r for r in identity_refs(conditioning) if r["method"] == _IP_ADAPTER]


def reference_refs(conditioning: dict) -> list[dict[str, Any]]:
    return [r for r in identity_refs(conditioning) if r["method"] == _REFERENCE]


def lora_refs(conditioning: dict) -> list[dict[str, Any]]:
    return [r for r in identity_refs(conditioning) if r["method"] == "lora"]


def instantid_refs(conditioning: dict) -> list[dict[str, Any]]:
    return [r for r in identity_refs(conditioning) if r["method"] == "instantid"]


def unimplemented_identity_methods(conditioning: dict) -> list[str]:
    return sorted({r["method"] for r in identity_refs(conditioning) if r["method"] in _UNIMPLEMENTED_METHODS})


def inpaint_from(conditioning: dict) -> str | None:
    value = conditioning.get("inpaint_from")
    return str(value) if value else None


def inpaint_region(conditioning: dict) -> str:
    return str(conditioning.get("inpaint_region") or "center")


def pipeline_kind(conditioning: dict) -> str:
    parts: list[str] = []
    if inpaint_from(conditioning):
        parts.append("inpaint")
    if pose_paths(conditioning):
        parts.append("controlnet")
    if ip_adapter_refs(conditioning):
        parts.append("ip")
    if reference_refs(conditioning):
        parts.append("reference")
    if lora_refs(conditioning):
        parts.append("lora")
    if instantid_refs(conditioning):
        parts.append("instantid")
    return "_".join(parts) or "base"


def resolve_ref(raw: str | Path) -> Path:
    """Resolve a contract ref to a real file.

    Order: the path as given (cwd / absolute), then the shipped sprite
    tree (``poses/...``, ``plates/...``), then the filename alone under
    those two sprite folders. Missing stays a refuse.
    """
    text = str(raw)
    given = Path(text)
    if given.is_file():
        return given.resolve()
    candidates = [_SPRITE_ROOT / text]
    # Bare filenames only — do not let poses/front.openpose.png steal
    # poses/turnaround/front.openpose.png.
    if given.parent == Path():
        candidates.extend(
            (
                _SPRITE_ROOT / "poses" / given.name,
                _SPRITE_ROOT / "plates" / given.name,
                _SPRITE_ROOT / "poses" / "turnaround" / given.name,
            )
        )
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
    raise FileNotFoundError(text)


def bind_refs(conditioning: dict, *, generator_id: str = "") -> dict:
    """Copy conditioning with every named ref resolved. Refuse if any is missing."""
    who = f"{generator_id} " if generator_id else ""
    out = dict(conditioning)
    try:
        out["pose_refs"] = [str(resolve_ref(p)) for p in pose_paths(out)]
        new_ids = []
        for raw in conditioning.get("identity_refs") or []:
            if not isinstance(raw, dict):
                new_ids.append(raw)
                continue
            plate = raw.get("plate")
            method = str(raw.get("method") or _IP_ADAPTER)
            if plate and method not in _SKIP_METHODS:
                new_ids.append({**raw, "plate": str(resolve_ref(plate))})
            else:
                new_ids.append(raw)
        if "identity_refs" in conditioning:
            out["identity_refs"] = new_ids
        src = inpaint_from(out)
        if src:
            out["inpaint_from"] = str(resolve_ref(src))
    except FileNotFoundError as err:
        raise PromptCraftError(
            "GATE_CONDITIONING_REF_MISSING",
            f"{who}conditioning ref {err!s} is not a readable file",
            hint="Pose-lock, identity-bind, and inpaint all refuse rather than "
            "render without the plate. Packaged plates live under the sprite "
            "subdomain (poses/, plates/).",
        ) from err
    return out


def assert_refs_readable(conditioning: dict, *, generator_id: str = "") -> dict:
    """Refuse before any model load if a named ref is not a readable file.

    Returns the conditioning with refs resolved to absolute paths so
    ``open_image`` does not depend on cwd.
    """
    return bind_refs(conditioning, generator_id=generator_id)


def refuse_unimplemented_identity(generator_id: str, conditioning: dict) -> None:
    methods = unimplemented_identity_methods(conditioning)
    if not methods:
        return
    raise PromptCraftError(
        "GATE_CONDITIONING_UNSUPPORTED",
        f"{generator_id} cannot apply identity method(s) {methods}: "
        "no encoder is wired for that method",
        hint="Set identity_ref.method to ip_adapter, lora, or instantid. "
        "method=none skips. method=reference is `pcraft recipe`.",
    )


def refuse_reference_identity(generator_id: str, conditioning: dict) -> None:
    """SDXL / local Flux do not run the Cloud recipe. method=reference is pcraft recipe."""
    if not reference_refs(conditioning):
        return
    raise PromptCraftError(
        "GATE_CONDITIONING_UNSUPPORTED",
        f"{generator_id} cannot apply identity method=reference: that is the "
        "Cloud Kontext stitch + left crop + fist-only Fill recipe",
        hint="Run `pcraft recipe` to emit the graph. SDXL stays on method=ip_adapter. "
        "Do not mask the bracer on the Fill pass.",
    )


def refuse_unmeasured_family(generator_id: str, family: str, conditioning: dict) -> None:
    """Flux refuses SDXL-shaped pose / IP-Adapter. Fill inpaint and method=reference are Flux's."""
    if pose_paths(conditioning):
        raise PromptCraftError(
            "GATE_CONDITIONING_UNSUPPORTED",
            f"{generator_id} (family={family}) cannot apply pose_refs as ControlNet. "
            "That is the SDXL encoder.",
            hint="Two-hand pose on Flux is the Cloud recipe (method=reference / pcraft recipe).",
        )
    if ip_adapter_refs(conditioning):
        raise PromptCraftError(
            "GATE_CONDITIONING_UNSUPPORTED",
            f"{generator_id} (family={family}) cannot apply method=ip_adapter. "
            "That is the SDXL encoder.",
            hint="Flux identity is method=reference (Cloud Kontext stitch + Fill).",
        )
    if lora_refs(conditioning):
        raise PromptCraftError(
            "GATE_CONDITIONING_UNSUPPORTED",
            f"{generator_id} (family={family}) cannot apply method=lora. "
            "That is the SDXL encoder.",
            hint="Load a LoRA on SDXL, or use method=reference on Flux.",
        )
    if instantid_refs(conditioning):
        raise PromptCraftError(
            "GATE_CONDITIONING_UNSUPPORTED",
            f"{generator_id} (family={family}) cannot apply method=instantid. "
            "That is the SDXL encoder.",
            hint="InstantID is the SDXL face lock. Flux identity is method=reference.",
        )


def open_image(path: str | Path):
    try:
        from PIL import Image  # type: ignore
    except ImportError as err:
        raise PromptCraftError(
            "DEP_IMAGE_MISSING",
            "opening a conditioning plate needs Pillow (the [image] extra)",
        ) from err
    return Image.open(path)


def region_box(width: int, height: int, region: str) -> tuple[int, int, int, int]:
    """Pixel box (left, top, right, bottom) for a named contract region. GPU-free."""
    if width <= 0 or height <= 0:
        raise PromptCraftError(
            "GATE_CONDITIONING_REF_MISSING",
            f"cannot build an inpaint mask for empty size {(width, height)}",
        )
    name = region.strip().lower()
    if name in {"head", "face"}:
        return (0, 0, width, max(1, int(height * 0.35)))
    if name in {"torso", "chest", "chest-center"}:
        return (int(width * 0.15), int(height * 0.30), int(width * 0.85), int(height * 0.70))
    if name in {"hands", "weapon", "hand"}:
        return (0, int(height * 0.55), width, height)
    if name == "fist":
        x0, y0, x1, y1 = _FIST
        left = int(width * x0)
        top = int(height * y0)
        right = max(left + 1, int(width * x1))
        bottom = max(top + 1, int(height * y1))
        return (left, top, right, bottom)
    return (int(width * 0.25), int(height * 0.25), int(width * 0.75), int(height * 0.75))


def mask_for_region(size: tuple[int, int], region: str):
    """White = inpaint this region. Lazy PIL."""
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError as err:
        raise PromptCraftError(
            "DEP_IMAGE_MISSING",
            "building an inpaint mask needs Pillow (the [image] extra)",
        ) from err
    width, height = size
    mask = Image.new("L", (width, height), 0)
    box = region_box(width, height, region)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    return mask
