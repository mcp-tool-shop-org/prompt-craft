"""Deterministic palette check. No model, no GPU.

A ``check_type=palette`` atom with hex ``enum`` colours scores how strongly
those colours are *present* in the image. Backdrop pixels are ignored: we
do not require the whole frame to live in the palette (a taupe studio plate
would fail that). Text enums (``gold heraldry``) are not colours — those
SKIP, they belong to SigLIP2.

family = ``palette-hist`` so this is never the generator's family.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from ....core.contract.compile_questions import Question
from ....errors import PromptCraftError

_NEAR = 36  # Euclidean RGB: mid-grey must not count as blood-red
_MIN_FRAC = 0.004  # ~0.4% of pixels is enough to count a colour as present


class PaletteVerifier:
    family = "palette-hist"
    tier = 0
    verifier_id = "palette.hist.v1"
    version = "v1"

    def score(self, image_path: str, question: Question) -> float | None:
        colours = _hex_colours(question.enum)
        if not colours:
            return None
        try:
            pixels = load_rgb(image_path)
        except PromptCraftError:
            raise
        except Exception as err:
            raise PromptCraftError(
                "RUNTIME_VERIFIER_CALL_FAILED",
                f"palette verifier could not read {image_path!r}: {err}",
                cause=err,
            ) from err
        if not pixels:
            return None
        hits = [_presence(pixels, rgb) for rgb in colours]
        return round(sum(hits) / len(hits), 4)


class Tier0Router:
    """Tier-0 door: palette atoms hit the histogram; everything else hits SigLIP2.

    family stays ``siglip2`` so family_guard and the existing plugin smoke test
    keep seeing one Tier-0 family. The histogram is a local function, not a
    second registered family.
    """

    family = "siglip2"
    tier = 0
    verifier_id = "tier0.router.v1"
    version = "v1"

    def __init__(self) -> None:
        from .siglip2_screen import SigLIP2Screen

        self._siglip = SigLIP2Screen()
        self._palette = PaletteVerifier()

    def score(self, image_path: str, question: Question) -> float | None:
        if question.check_type.value == "palette":
            return self._palette.score(image_path, question)
        return self._siglip.score(image_path, question)


def _hex_colours(enum: list[str] | None) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for raw in enum or []:
        text = raw.strip()
        if not text.startswith("#"):
            continue
        h = text[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) != 6:
            continue
        try:
            out.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
        except ValueError:
            continue
    return out


def _presence(pixels: list[tuple[int, int, int]], target: tuple[int, int, int]) -> float:
    n = len(pixels)
    if n == 0:
        return 0.0
    hits = 0
    tr, tg, tb = target
    for r, g, b in pixels:
        if ((r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2) ** 0.5 <= _NEAR:
            hits += 1
    frac = hits / n
    if frac >= _MIN_FRAC:
        return 1.0
    return frac / _MIN_FRAC


def load_rgb(path: str | Path) -> list[tuple[int, int, int]]:
    """RGB pixels. PIL if present; else filter-0 8-bit RGB PNG (write_solid_png)."""
    try:
        from PIL import Image  # type: ignore

        im = Image.open(path).convert("RGB")
        return list(im.getdata())
    except ImportError:
        return _load_png_filter0(path)


def _load_png_filter0(path: str | Path) -> list[tuple[int, int, int]]:
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PromptCraftError(
            "DEP_IMAGE_MISSING",
            "palette verifier needs Pillow to read this image (not a filter-0 PNG)",
        )
    pos = 8
    width = height = None
    idat = b""
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        typ = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if typ == b"IHDR":
            width, height, bit, color, *_rest = struct.unpack(">IIBBBBB", chunk)
            if bit != 8 or color != 2:
                raise PromptCraftError(
                    "DEP_IMAGE_MISSING",
                    "stdlib PNG reader only handles 8-bit RGB; install Pillow",
                )
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    if width is None or height is None:
        raise PromptCraftError("RUNTIME_VERIFIER_CALL_FAILED", f"PNG {path} has no IHDR")
    raw = zlib.decompress(idat)
    row_bytes = 1 + width * 3
    pixels: list[tuple[int, int, int]] = []
    for y in range(height):
        row = raw[y * row_bytes : (y + 1) * row_bytes]
        if not row:
            break
        if row[0] != 0:
            raise PromptCraftError(
                "DEP_IMAGE_MISSING",
                "stdlib PNG reader only handles filter 0; install Pillow",
            )
        body = row[1:]
        for x in range(width):
            i = x * 3
            pixels.append((body[i], body[i + 1], body[i + 2]))
    return pixels
