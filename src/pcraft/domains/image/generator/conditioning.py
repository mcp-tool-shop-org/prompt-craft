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
# F-916e73b6: this used to be a DENY-list (_UNIMPLEMENTED_METHODS) and it was EMPTY, so
# refuse_unimplemented_identity() was a structurally dead refusal called on both shipped generate
# paths. core/contract/schema.py declares `method: str` with the legal values living only in a
# trailing comment, so an unrecognised name ('ip-adapter', 'ipadapter', 'pulid', 'faceid') passes
# contract validation, is resolved and existence-checked by bind_refs, then dropped by every
# method-specific accessor below -- while the receipt still stamps the resolved plate path. An
# ALLOW-list cannot go stale that way: a method nobody wired is refused by name.
_SUPPORTED_METHODS = frozenset({_IP_ADAPTER, _REFERENCE, "lora", "instantid", *_SKIP_METHODS})
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


def skipped_identity_refs(conditioning: dict) -> list[dict[str, Any]]:
    """Plate-carrying identity refs whose method is a documented SKIP, with the method resolved.

    F-60b76831: the complement of ``identity_refs`` -- the refs every method-specific accessor
    above deliberately drops. Reads the RAW refs for the same reason ``declared_methods`` does: a
    skip is invisible to every filtered view by construction, and a receipt that can only show the
    filtered views cannot say a skip happened.
    """
    out: list[dict[str, Any]] = []
    for raw in conditioning.get("identity_refs") or []:
        if not isinstance(raw, dict) or not raw.get("plate"):
            continue
        method = str(raw.get("method") or _IP_ADAPTER)
        if method in _SKIP_METHODS:
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


def declared_methods(conditioning: dict) -> list[str]:
    """Every method named on a raw identity_ref that carries a plate.

    Reads the RAW refs, not ``identity_refs()``: the supported-method check has to see a method the
    skip/filter layers would otherwise drop, or the drop is exactly the silence being refused.
    """
    out: list[str] = []
    for raw in conditioning.get("identity_refs") or []:
        if not isinstance(raw, dict) or not raw.get("plate"):
            continue
        out.append(str(raw.get("method") or _IP_ADAPTER))
    return out


def unsupported_identity_methods(conditioning: dict) -> list[str]:
    """Methods named on a plate-carrying ref that no encoder in this repo implements."""
    return sorted({m for m in declared_methods(conditioning) if m not in _SUPPORTED_METHODS})


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


def is_packaged_ref(path: str | Path) -> bool:
    """True when a RESOLVED ref points inside the installed sprite tree, not a working directory.

    ``resolve_ref`` searches the packaged ``poses/`` and ``plates/`` folders after trying the path
    as given, so a contract naming ``plates/ashen-reaver-front.png`` resolves to a file inside
    site-packages on an installed build. Anything that has to hand those files to something else --
    the Cloud upload manifest (F-0caa740d), a docs snippet -- must be able to SAY that, rather than
    print an absolute path that reads as if it were copyable out of the operator's own project.
    Answering it here is the point: this module owns the resolution rule, so it is the only place
    that cannot be wrong about which of its own search roots produced a hit.
    """
    try:
        Path(path).resolve().relative_to(_SPRITE_ROOT)
    except (ValueError, OSError):
        return False
    return True


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
    """Refuse any identity method outside ``_SUPPORTED_METHODS``, naming the offending value.

    F-916e73b6: silently dropping the lock while the receipt stamps the resolved plate is the one
    outcome this function exists to prevent. It is called on both shipped generate paths.
    """
    methods = unsupported_identity_methods(conditioning)
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


def refuse_unmeasured_identity_family(generator_id: str, family: str, conditioning: dict) -> None:
    """The identity half of ``refuse_unmeasured_family``: ip_adapter / lora / instantid.

    F-43da2300 (ordering half): flux_generator used to test ``reference_refs`` BEFORE calling
    ``refuse_unmeasured_family``, so a conditioning carrying both a reference ref and an
    ip_adapter/lora/instantid ref wrote the Cloud recipe and raised GATE_CLOUD_SUBMIT without ever
    refusing the wrong-family lock. Split out so the recipe path can refuse those locks first
    WITHOUT also refusing the pose map -- which on the reference path is the recipe's own
    ImageStitch input, not an SDXL ControlNet request.
    """
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


def refuse_unmeasured_family(generator_id: str, family: str, conditioning: dict) -> None:
    """Flux refuses SDXL-shaped pose / IP-Adapter. Fill inpaint and method=reference are Flux's."""
    if pose_paths(conditioning):
        raise PromptCraftError(
            "GATE_CONDITIONING_UNSUPPORTED",
            f"{generator_id} (family={family}) cannot apply pose_refs as ControlNet. "
            "That is the SDXL encoder.",
            hint="Two-hand pose on Flux is the Cloud recipe (method=reference / pcraft recipe).",
        )
    refuse_unmeasured_identity_family(generator_id, family, conditioning)


def open_image(path: str | Path):
    try:
        from PIL import Image  # type: ignore
    except ImportError as err:
        raise PromptCraftError(
            "DEP_IMAGE_MISSING",
            "opening a conditioning plate needs Pillow (the [image] extra)",
        ) from err
    return Image.open(path)


SUPPORTED_REGIONS = frozenset(
    {"head", "face", "torso", "chest", "chest-center", "hands", "weapon", "hand", "fist", "center"}
)
"""Region names ``region_box`` recognises BY NAME. Edit this and ``region_box`` together.

F-2c77d698. ``region_box`` answers every name, because its caller until now was the inpaint
repair, whose ``inpaint_region`` defaults to the string ``"center"`` -- so a trailing "return a
centre box" arm is correct THERE. It is not correct for a gate: a contract-authored
``spatial.ref`` is free text, and scoring ``shouldre`` on a guessed centre window produces a
verdict that reads exactly like a measured one. Consumers that must not guess ask
``is_supported_region`` first and refuse by name, the same discipline ``_SUPPORTED_METHODS``
applies to ``identity_ref.method``.

``center`` is listed deliberately: it is the NAME of the box the default arm returns and the
value ``inpaint_region`` already defaults to, so it is a recognised region rather than a
fall-through. Every other unlisted name reaches that arm by accident, which is the difference
this set exists to draw.
"""


def is_supported_region(region: str) -> bool:
    """Whether ``region_box`` recognises this name, or would merely fall through to its default."""
    return region.strip().lower() in SUPPORTED_REGIONS


def region_box(width: int, height: int, region: str) -> tuple[int, int, int, int]:
    """Pixel box (left, top, right, bottom) for a named contract region. GPU-free.

    Deliberately total: an unrecognised name gets the centre box, because the inpaint repair has
    to paint SOMETHING and ``inpaint_region`` defaults to a name ("center") that lands here. A
    caller that must not guess -- the gate -- checks ``is_supported_region`` first.
    """
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
