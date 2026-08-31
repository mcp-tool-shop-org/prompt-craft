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

    ``family`` stays ``siglip2`` so family_guard and the existing plugin smoke test keep seeing one
    Tier-0 family. The histogram is a local delegate, not a second registered family.

    F-f68f59ff: the router used to declare ``family='siglip2'``, ``verifier_id='tier0.router.v1'``
    for EVERY Tier-0 score, including ones produced by ``PaletteVerifier`` -- a deterministic stdlib
    RGB histogram that declares ``family='palette-hist'``, ``verifier_id='palette.hist.v1'``. So a
    palette atom's evidence line attributed a no-model histogram result to the SigLIP2 neural
    family. The single ``family`` the guard needs is unchanged and the reason it is single is stated
    here rather than only in a docstring elsewhere.

    F-64b4f422: that fix recorded the delegate on ``last_delegate`` and documented it as existing
    "so the receipt can say what ran" -- but NOTHING in src/ read it. ``core/gate/harness.py`` stamps
    ``AtomVerdict.verifier_id`` from ``verifier.verifier_id``, and the only readers of
    ``last_delegate`` were this module's own tests. Measured end to end, ``palette.hist.v1`` appeared
    nowhere in the AtomVerdict or the GateTranscript: the attribution defect was verbatim intact
    behind a field that looked live.

    So ``verifier_id`` is now the answer to "who produced the score I just returned", which is
    exactly what ``AtomVerdict.verifier_id`` means. The harness reads it immediately after calling
    ``score()``, so a palette line names the histogram and a screened line names SigLIP2 -- no widen
    -ing of the core transcript required. ``family`` deliberately does NOT follow: family_guard must
    keep seeing one Tier-0 family, and the transcript carries no family field for this to contradict.
    """

    family = "siglip2"
    tier = 0
    version = "v1"
    # What a router that has not scored anything yet answers -- the tier registry and the plugin
    # smoke test read verifier_id before any image exists.
    router_id = "tier0.router.v1"
    # The one Tier-0 family family_guard sees. Named on the receipt so "siglip2" on a palette line
    # reads as "the router's guard family", not "SigLIP2 measured this".
    family_is_shared_for_guard = True

    def __init__(self) -> None:
        from .siglip2_screen import SigLIP2Screen

        self._siglip = SigLIP2Screen()
        self._palette = PaletteVerifier()
        self.last_delegate: dict[str, str] | None = None

    @property
    def verifier_id(self) -> str:
        """The sub-verifier that produced the most recent score; the router before there is one."""
        if self.last_delegate is None:
            return self.router_id
        return self.last_delegate["verifier_id"]

    def _record(self, delegate) -> None:
        self.last_delegate = {
            "verifier_id": delegate.verifier_id,
            "version": delegate.version,
            "family": delegate.family,
        }

    def score(self, image_path: str, question: Question) -> float | None:
        if question.check_type.value == "palette":
            # Recorded BEFORE the call, not after: the harness also reads verifier_id to name who
            # raised or who was unavailable, and a delegate left over from the previous atom would
            # put the wrong instrument on that line too.
            self._record(self._palette)
            score = self._palette.score(image_path, question)
            if score is not None:
                return score
            # The enum carried no hex colours ('gold heraldry'). palette_verifier's module docstring
            # says those "belong to SigLIP2" -- but routing on check_type ALONE returned None here,
            # so the atom was skipped at Tier-0 entirely instead of being screened. Fall through.
        self._record(self._siglip)
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
    """RGB pixels. PIL if present; else filter-0 8-bit RGB PNG (write_solid_png).

    F-f6646790: the try block used to span three statements -- the import, ``Image.open().convert``,
    and ``list(im.getdata())`` -- so an ImportError raised from INSIDE Pillow during open/convert/
    decode (a lazy codec or plugin import failing) was misread as "Pillow is not installed" and
    silently rerouted to the stdlib reader, or reported DEP_IMAGE_MISSING "needs Pillow" about an
    installed Pillow. Only the import statement may be guarded; a decode-time ImportError has to
    propagate so ``PaletteVerifier.score`` classifies it as RUNTIME_VERIFIER_CALL_FAILED with the
    real cause attached.

    F-09db27bc: F-5ca8ecd3's declared-vs-decoded completeness check was added to the stdlib fallback
    ONLY -- the branch that runs when Pillow is absent. The Pillow branch is the one every [image] /
    GPU install takes, and Pillow's own truncation guard is measurably not sufficient: a VALID but
    short zlib stream (a nonconforming encoder that finalises deflate early) decodes without error
    and Pillow PADS the missing scanlines with BLACK. The verifier then scored those invented pixels
    -- a ``#000000`` atom measured 1.0 on an image containing no black pixels. Both branches now
    answer the same question before trusting any decode.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return _load_png_filter0(path)
    _assert_png_not_short(path)
    im = Image.open(path).convert("RGB")
    return list(im.getdata())


# IHDR colour type -> samples per pixel. Used only to size a scanline; the Pillow branch reads every
# real-world PNG, so this cannot be narrowed to the fallback's 8-bit-RGB-only case.
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _short_png_error(path: str | Path, width: int, height: int, decoded: int) -> PromptCraftError:
    """The one wording for "the file declares more image than it carries".

    Both readers raise through here so the asymmetry that was F-09db27bc cannot come back as a
    difference in phrasing: the same bytes must refuse the same way whether Pillow is installed
    or not.
    """
    return PromptCraftError(
        "RUNTIME_VERIFIER_CALL_FAILED",
        f"PNG {path} declares {width}x{height} ({width * height} pixels) but only "
        f"{decoded} decoded",
        hint="The file is truncated or its IDAT is short (an interrupted write, a partial "
        "copy). A palette score over a fraction of the image is not a measurement.",
    )


def _png_complete_rows(data: bytes) -> tuple[int, int, int] | None:
    """``(width, height, whole scanlines actually present in the IDAT)``, or None if unmeasurable.

    Deliberately lenient: this guards a branch that reads every format Pillow reads, so anything it
    cannot parse exactly -- a non-PNG, an Adam7 interlace, an unknown colour type, corrupt deflate --
    returns None and is left to Pillow. The guard may only ever refuse on a POSITIVE measurement
    that the image is short; a false refusal here would break the shipped path it protects.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    width = height = bit = color = None
    idat = b""
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        typ = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if typ == b"IHDR":
            if len(chunk) < 13:
                return None
            width, height, bit, color, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk[:13]
            )
            if compression != 0 or filter_method != 0 or interlace != 0:
                return None  # Adam7 rows are not a flat sequence; do not guess at a count
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    if not width or not height or color not in _PNG_CHANNELS or bit not in (1, 2, 4, 8, 16):
        return None
    row_bytes = 1 + (width * bit * _PNG_CHANNELS[color] + 7) // 8
    try:
        # decompressobj, not decompress: a truncated deflate stream must yield what it has rather
        # than raise, because "it has fewer rows than IHDR promised" is exactly the measurement.
        raw = zlib.decompressobj().decompress(idat)
    except zlib.error:
        return None
    return (width, height, min(height, len(raw) // row_bytes))


def _assert_png_not_short(path: str | Path) -> None:
    """Refuse a PNG whose IDAT carries fewer scanlines than its IHDR declares."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return  # not readable from here; let Pillow raise its own, better-worded error
    measured = _png_complete_rows(data)
    if measured is None:
        return
    width, height, rows = measured
    if rows < height:
        raise _short_png_error(path, width, height, rows * width)


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
            # F-5ca8ecd3: compression / filter-method / interlace used to be discarded into
            # *_rest, so an Adam7 layout would have been decoded as a plain row sequence.
            width, height, bit, color, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            if bit != 8 or color != 2:
                raise PromptCraftError(
                    "DEP_IMAGE_MISSING",
                    "stdlib PNG reader only handles 8-bit RGB; install Pillow",
                )
            if interlace != 0:
                raise PromptCraftError(
                    "DEP_IMAGE_MISSING",
                    f"stdlib PNG reader cannot decode interlaced (Adam7) PNGs "
                    f"(interlace={interlace}); install Pillow",
                )
            if compression != 0 or filter_method != 0:
                raise PromptCraftError(
                    "DEP_IMAGE_MISSING",
                    f"stdlib PNG reader only handles compression 0 / filter method 0 "
                    f"(got {compression}/{filter_method}); install Pillow",
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
        if len(row) != row_bytes:
            break  # short IDAT -- the completeness check below refuses; never a partial score
        if row[0] != 0:
            raise PromptCraftError(
                "DEP_IMAGE_MISSING",
                "stdlib PNG reader only handles filter 0; install Pillow",
            )
        body = row[1:]
        for x in range(width):
            i = x * 3
            pixels.append((body[i], body[i + 1], body[i + 2]))
    # F-5ca8ecd3: the row loop used to break on the first empty slice and return whatever it had,
    # and nothing compared the count against the IHDR. _presence() then produced an ordinary float
    # in [0,1] over a fraction of the image and the receipt could not tell the difference -- a
    # silently-wrong verdict in the one verifier that is supposed to be deterministic.
    if len(pixels) != width * height:
        # F-09db27bc: shared wording with the Pillow branch's guard -- one law, one sentence.
        raise _short_png_error(path, width, height, len(pixels))
    return pixels
