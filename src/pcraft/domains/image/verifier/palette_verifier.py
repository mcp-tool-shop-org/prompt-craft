"""Deterministic palette check. No model, no GPU.

A ``check_type=palette`` atom with hex ``enum`` colours scores how strongly
those colours are *present* in the image. Backdrop pixels are ignored: we
do not require the whole frame to live in the palette (a taupe studio plate
would fail that). Text enums (``gold heraldry``) are not colours — those
SKIP, they belong to SigLIP2.

A member that starts with ``#`` and is NOT a colour is neither of those things: it is an authoring
error, and it is refused by name (``CONTRACT_PALETTE_ENUM_INVALID``) rather than dropped, because a
dropped member narrows the atom's declared check with nothing on the receipt saying so. An enum that
mixes hex and text belongs to no single instrument and is refused too
(``CONTRACT_PALETTE_ENUM_MIXED``). See ``_colours_or_refuse``.

An atom that declares WHERE it must hold is measured THERE (F-2c77d698): ``spatial.kind=region``
crops to ``conditioning.region_box`` -- the same box the inpaint repair paints -- before counting
pixels, and the verdict says which window it came off. This is the one verifier in the domain that
can honour a region honestly today, because it has no model whose calibration a crop would move.
An atom with NO ``spatial`` is measured over the whole frame exactly as before: ``_presence``
compares a fraction of the MEASURED WINDOW against ``_MIN_FRAC``, so cropping by default would
silently redefine "present" for the shipped palette atom. See ``region.py``.

family = ``palette-hist`` so this is never the generator's family.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from ....core.contract.compile_questions import Question
from ....errors import PromptCraftError
from .region import crop_pixels, declared_region, describe_window, region_window

_NEAR = 36  # Euclidean RGB: mid-grey must not count as blood-red
_MIN_FRAC = 0.004  # ~0.4% of pixels is enough to count a colour as present


class PaletteVerifier:
    family = "palette-hist"
    tier = 0
    verifier_id = "palette.hist.v1"
    version = "v1"

    # F-2c77d698. A score measured over a DECLARED REGION is not on the full-frame scale --
    # ``_presence`` compares a hit fraction of the measured window against ``_MIN_FRAC``, so
    # cropping changes what "present" means. Two windows therefore mean two instrument identities,
    # and the receipt must be able to tell them apart: stamping a cropped number with the id that
    # has always meant "full frame" would re-decide region atoms under a threshold table whose
    # ``fingerprint()`` hashes only band values and would report NO drift.
    #
    # Only the VERSION segment moves. ``"<band>.<instrument>.<version>"`` is the convention
    # Tier0Router's docstring calls load-bearing and ``harness._band_key`` actually keys zoning on,
    # so ``palette`` stays exactly where it is: a region score is graded on the palette band, and
    # THAT is the part still owed a measurement. The shipped table already says its palette band is
    # a placeholder ("Recalibrate against ~50-100 labelled sprites per check_type"), and the
    # workflow that would fit a separate region band now exists -- ``core/gate/holdout.py`` fits a
    # band per band key from labelled rows. What does not exist is labelled REGION-SCORED rows, and
    # a band invented without them is the thing that field warns against. So the window rides the
    # receipt (``describe_window``) until someone measures it, and a reader can always see which
    # scale a number came off.
    region_verifier_id = "palette.hist.v2"
    region_version = "v2"

    def __init__(self) -> None:
        # F-1675985a. The per-colour hit vector behind the most recent score, or None when the most
        # recent call produced no score (a text enum, an empty image, a refusal). Reset at the top
        # of every score() rather than only written on success: a vector left over from the previous
        # atom is the F-64b4f422 defect (a field that looks live and answers about something else).
        self.last_breakdown: list[dict] | None = None
        # The window the most recent score measured, or None for a full-frame score. Reset in the
        # same place and for the same reason as the breakdown above.
        self.last_region: dict | None = None

    def verifier_id_for(self, question: Question) -> str:
        """Who will produce this atom's score: the full-frame histogram, or the region one.

        Answered from the QUESTION rather than from the last call, so ``Tier0Router`` can record
        the delegate BEFORE scoring -- which it does deliberately, since the harness also reads
        ``verifier_id`` to name who raised or who was unavailable, and a delegate left over from
        the previous atom would put the wrong instrument on that line too.
        """
        return self.region_verifier_id if declared_region(question) else self.verifier_id

    def version_for(self, question: Question) -> str:
        """The version half of ``verifier_id_for``. Same derivation, same reason."""
        return self.region_version if declared_region(question) else self.version

    def score(self, image_path: str, question: Question) -> float | None:
        self.last_breakdown = None
        self.last_region = None
        colours = _colours_or_refuse(question)
        if not colours:
            return None
        try:
            pixels, width, height = load_rgb_sized(image_path)
        except PromptCraftError:
            raise
        except Exception as err:
            raise PromptCraftError(
                "RUNTIME_VERIFIER_CALL_FAILED",
                f"palette verifier could not read {image_path!r}: {err}",
                # F-1d5992bd: the three model-backed siblings in this verifier family
                # (VQAScoreVerifier.score, SigLIP2Screen.score, DSGVerifier._ask) each name "CUDA
                # OOM mid-run" here. This is the one Tier-0 delegate with no model and no GPU (see
                # the module docstring), so inheriting the shared fallback's model-shaped wording
                # would point the operator at an instrument that does not exist on this path.
                hint="The histogram verifier has no model and no GPU -- this is a file-read or "
                "decode failure (missing file, corrupt or oversized PNG, a PNG the stdlib reader "
                "cannot decode), not a CUDA or model problem. Check the cause.",
                cause=err,
            ) from err
        if not pixels:
            return None
        # F-2c77d698. Gated on the field being PRESENT, never applied by default: the shipped
        # palette atom carries no spatial, and cropping it would silently redefine "present" for
        # the one verifier in this domain that is supposed to be deterministic.
        region = declared_region(question)
        if region is not None:
            box = region_window(width, height, region, atom_id=question.atom_id)
            pixels = crop_pixels(pixels, width, height, box)
            self.last_region = {"region": region, "box": box, "frame": (width, height)}
            if not pixels:
                # An image too small to contain the declared window (a 1-pixel-tall plate has no
                # head). SKIPPED, the same answer the empty-image arm above gives: the atom did not
                # fail, it could not be measured, and the harness records that distinctly.
                return None
        hits = [_presence(pixels, rgb) for rgb in colours]
        # Echoed as AUTHORED, for the reason CONTRACT_PALETTE_ENUM_MIXED already echoes the written
        # members: the operator has to find these strings in the contract, and '#00FF00' is not
        # '#00ff00' to a text search. strict=True because a length mismatch between the authored
        # members and the parsed colours would mean _colours_or_refuse let a malformed member
        # through, which is precisely what it exists to refuse.
        self.last_breakdown = [
            {"hex": written, "rgb": rgb, "hit": round(hit, 4)}
            for written, rgb, hit in zip(_written_hex(question.enum), colours, hits, strict=True)
        ]
        return round(sum(hits) / len(hits), 4)

    def breakdown_detail(self) -> str | None:
        """What a multi-colour verdict cannot say from the mean alone: which colours were missing.

        F-1675985a. ``score`` collapsed a genuinely per-colour measurement into one float, so a
        FAIL on the shipped ``['#3a3a3a','#d9d4c8','#7a1f1f']`` atom read only 'score 0.3333 ->
        FAIL (band palette)' -- indistinguishable from 'all three partially present'. The aggregate
        is untouched (the calibration bands grade exactly what they graded before); this is the
        additional sentence beside it.

        ``_presence`` returns 1.0 once a colour covers ``_MIN_FRAC`` of the frame, 0.0 when it is
        wholly absent, and the ratio in between -- so those three cases are named differently
        rather than all rendered as one number the reader has to interpret.
        """
        if not self.last_breakdown:
            return None
        expected = ", ".join(entry["hex"] for entry in self.last_breakdown)
        short = [entry for entry in self.last_breakdown if entry["hit"] < 1.0]
        if not short:
            body = f"expected {expected}; all present"
        else:
            named = ", ".join(
                f"{entry['hex']} "
                + ("absent" if entry["hit"] <= 0.0 else "below the presence floor")
                + f" (hit {entry['hit']:.2f})"
                for entry in short
            )
            body = f"expected {expected}; {named}"
        # F-2c77d698: the window LEADS. "expected #ffffff; #ffffff absent" over a crop and the same
        # sentence over the whole frame are different claims, and the reader has to know which one
        # they are holding before the colours mean anything.
        if self.last_region is not None:
            window = describe_window(
                self.last_region["region"], self.last_region["box"], *self.last_region["frame"]
            )
            return f"{window}; {body}"
        return body


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

    F-00cfd3f8: naming the instrument was not enough, because nothing named the BAND that judged it.
    ``harness.evaluate`` zoned on ``q.check_type.value``, never on the delegate that produced the
    number, while ``score()`` below deliberately routes a ``check_type=palette`` atom to SigLIP2
    whenever the enum carries no hex colours. The two bands are not interchangeable and the shipped
    calibration says so in its own notes: palette high=0.85/low=0.50, siglip2 high=0.10/low=0.01,
    "siglip2 sigmoid is uncalibrated/pixel-art-tuned: >0.10 strong match, <0.01 absent". MEASURED end
    to end with SigLIP2 stubbed: a text-enum palette atom scoring 0.30 -- three times that table's
    own strong-match threshold -- returned zone=FAIL, overall=FAIL, reason 'score 0.3000 -> FAIL',
    with 'palette' appearing nowhere in it; 0.12 -> FAIL, 0.60 -> UNCERTAIN, and only >= 0.85 passes,
    which the calibration says SigLIP2 does not produce.

    THE VALUE CONVENTION (load-bearing, agreed with core/gate). A Tier-0 delegate's ``verifier_id``
    is ``"<band>.<instrument>.<version>"``, and ``<band>`` is a key in the shipped threshold table:
    ``palette.hist.v1`` -> ``palette``, ``siglip2.screen.v1`` -> ``siglip2``. Because ``verifier_id``
    already follows the delegate, that one string carries both "who measured this" and "on whose
    scale", so instrument-aware zoning needs no new field on the transcript. ``band_key`` below is
    the same derivation spelled out on this side of the boundary; it is the router's statement of
    the convention, not a second channel. A delegate whose id does not name a band must never be
    added -- zoning would silently fall back to the table's ``default``.
    """

    family = "siglip2"
    tier = 0
    version = "v1"
    # What a router that has not scored anything yet answers -- the tier registry and the plugin
    # smoke test read verifier_id before any image exists. Deliberately NOT band-shaped: there is no
    # band until a delegate has run, and the harness only reads verifier_id after score() returns.
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

    @property
    def band_key(self) -> str:
        """The calibration band the most recent score belongs on -- the delegate's, not the atom's.

        Derived from ``verifier_id`` rather than stored, so the two can never disagree: this is the
        SAME derivation instrument-aware zoning applies on the harness side, written down here so
        the convention is code on both sides of the boundary instead of folklore on one.
        """
        return self.verifier_id.split(".", 1)[0]

    @property
    def last_breakdown(self) -> list[dict] | None:
        """The per-colour hits behind the most recent score -- None when SigLIP2 produced it.

        F-1675985a. DERIVED from ``last_delegate`` rather than stored, exactly like ``band_key``
        above and for the same reason: a ``check_type=siglip2`` atom never calls the histogram at
        all, so a stored copy would keep answering about whichever palette atom ran last. Gating on
        the recorded delegate makes "the histogram did not measure this one" and "the histogram
        measured this one and found nothing" different answers instead of the same stale list.
        """
        if self.last_delegate is None:
            return None
        # Gated on the FAMILY, not on a literal id (F-2c77d698): the histogram now answers to two
        # ids, one per window, and comparing against a single one of them would report "SigLIP2
        # produced this" for every region-scored palette atom. The family is the delegate's stable
        # identity -- palette-hist is the histogram whichever window it measured.
        if self.last_delegate["family"] != self._palette.family:
            return None
        return self._palette.last_breakdown

    def score_detail(self, image_path: str | None = None, question: Question | None = None) -> str | None:
        """The operator-facing sentence for the most recent score, or None if there is none.

        The reader ``last_breakdown`` needs so it is not the stranded field F-64b4f422 named on
        ``last_delegate``: this is where a palette FAIL becomes "expected #3a3a3a, #d9d4c8, #7a1f1f;
        #7a1f1f absent (hit 0.00)" instead of only a mean. The other half of that seam has since
        landed on the core side: ``AtomVerdict.detail`` exists and ``harness._detail_for`` looks
        this method up by name, so the value now reaches the transcript. It still lives on the
        router, which is the object the harness and the plugin already hold.

        F-2c77d698: the two OPTIONAL arguments exist because ``_detail_for`` prefers the
        ``(image_path, question)`` signature and falls back to the no-argument one. Both are
        accepted and the no-argument call keeps answering exactly as it did. The question is what
        lets a SigLIP2-decided atom carry the screen's own note instead of dropping it: the harness
        asks the DECIDING instrument, and for a Tier-0 atom that is this router.
        """
        if self.last_breakdown is None:
            # Not the histogram's verdict. If SigLIP2 decided it, its refusal-of-scope note is the
            # only thing anyone can say about a region it did not honour, so pass the question on.
            if question is None:
                return None
            detail = getattr(self._siglip, "score_detail", None)
            return detail(image_path, question) if callable(detail) else None
        return self._palette.breakdown_detail()

    def _record(self, delegate, question: Question) -> None:
        """Snapshot who is about to score. Region-aware, because the histogram has two ids.

        ``verifier_id_for`` / ``version_for`` are asked of the QUESTION, so this stays a
        before-the-call record (see ``score``) rather than becoming an after-the-fact read of
        whatever the delegate last did. A delegate without those methods -- SigLIP2, or an
        injected stand-in -- answers from its class attributes exactly as before.
        """
        resolve_id = getattr(delegate, "verifier_id_for", None)
        resolve_version = getattr(delegate, "version_for", None)
        self.last_delegate = {
            "verifier_id": resolve_id(question) if callable(resolve_id) else delegate.verifier_id,
            "version": resolve_version(question) if callable(resolve_version) else delegate.version,
            "family": delegate.family,
        }

    def score(self, image_path: str, question: Question) -> float | None:
        if question.check_type.value == "palette":
            # Recorded BEFORE the call, not after: the harness also reads verifier_id to name who
            # raised or who was unavailable, and a delegate left over from the previous atom would
            # put the wrong instrument on that line too.
            self._record(self._palette, question)
            score = self._palette.score(image_path, question)
            if score is not None:
                return score
            # The enum carried no hex colours ('gold heraldry'). palette_verifier's module docstring
            # says those "belong to SigLIP2" -- but routing on check_type ALONE returned None here,
            # so the atom was skipped at Tier-0 entirely instead of being screened. Fall through.
            #
            # A member that LOOKS like a colour and is not never reaches this line: _colours_or_refuse
            # raises above (F-411f3f58), so the fall-through means "these are words", never "one of
            # these was a typo". That matters here specifically, because crossing to SigLIP2 also
            # crosses to the siglip2 BAND (F-00cfd3f8) and a band change must be a decision, not an
            # accident of parsing.
        # F-00cfd3f8: recorded BEFORE the call on this arm too, so the fall-through verdict carries
        # the SigLIP2 family value -- siglip2.screen.v1, band_key 'siglip2'. This is the whole
        # channel instrument-aware zoning keys on: cross the delegate and the band crosses with it.
        self._record(self._siglip, question)
        return self._siglip.score(image_path, question)


def _parse_hex(text: str) -> tuple[int, int, int] | None:
    """``#rgb`` / ``#rrggbb`` -> RGB, or None if the body is not a colour."""
    h = text[1:]
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _written_hex(enum: list[str] | None) -> list[str]:
    """The ``#``-prefixed enum members exactly as authored, in declaration order.

    Order-aligned with ``_split_enum``'s ``colours`` for anything that actually scores: a ``#``
    member that does not parse is a refusal (F-411f3f58) and an enum mixing hex with text is a
    refusal too, so once ``_colours_or_refuse`` returns, these are the same members twice.
    """
    return [m for m in (enum or []) if m.strip().startswith("#")]


def _split_enum(enum: list[str] | None) -> tuple[list[tuple[int, int, int]], list[str], list[str]]:
    """``(colours, text members, malformed '#' members)``.

    F-411f3f58: this used to be one function that returned only the first list and dropped the
    other two on the floor, so a one-character typo in a hex colour took the atom off the
    deterministic verifier entirely with nothing recording the drop -- the F-916e73b6 defect class
    (silent drop of a declared constraint while the receipt still reads normal) landing on the enum
    field instead of the method field. The three outcomes are now distinguishable at the call site
    because they mean three different things, and only one of them is a legal drop.
    """
    colours: list[tuple[int, int, int]] = []
    text: list[str] = []
    malformed: list[str] = []
    for raw in enum or []:
        member = raw.strip()
        if not member:
            continue
        if not member.startswith("#"):
            # No '#' at all is the documented text-enum route ("gold heraldry"), not a typo.
            text.append(member)
            continue
        rgb = _parse_hex(member)
        if rgb is None:
            malformed.append(raw)
        else:
            colours.append(rgb)
    return colours, text, malformed


def _colours_or_refuse(question: Question) -> list[tuple[int, int, int]]:
    """The enum's colours, or a named refusal. Never a silently narrowed check.

    F-411f3f58. MEASURED before the fix: ``enum=['#8B000']`` (five hex digits) parsed 0/1,
    ``['#8B00000']`` 0/1, ``['#gggggg']`` 0/1, and the mixed ``['#8B000','#8B0000']`` parsed 1/2 and
    scored over the survivor alone. End to end on a pure-red plate, ``enum=['#FF0000']`` scores 1.0
    from ``palette.hist.v1`` while ``['#FF000']`` -- the same colour, one digit short -- returned
    None here, fell through to SigLIP2, and came back as an ordinary FAIL (or, with SigLIP2 absent,
    SKIPPED / overall UNAVAILABLE). Never an auto-pass, but never the measurement the contract asked
    for either, and nothing in either receipt named the typo. Reachability is not hypothetical: the
    shipped ``example.faction.contract.json`` carries a ``check_type=palette`` atom whose enum is the
    hand-written ``['#3a3a3a','#d9d4c8','#7a1f1f']``, so hex strings here are authored by hand.

    A member that starts with ``#`` and does not yield a colour is an authoring error, refused BY
    NAME -- the same shape as ``refuse_unimplemented_identity`` refusing an unrecognised method
    rather than dropping the lock. A member with no ``#`` keeps the documented text-enum route.
    """
    colours, text, malformed = _split_enum(question.enum)
    if malformed:
        raise PromptCraftError(
            "CONTRACT_PALETTE_ENUM_INVALID",
            f"palette atom {question.atom_id!r} declares enum member(s) {malformed} that start "
            "with '#' but are not colours",
            hint="A '#'-prefixed enum member must be #rgb or #rrggbb. Fix the typo, or drop the "
            "'#' if it was meant as a text enum (those are screened by SigLIP2). Dropping it "
            "silently would narrow the atom's declared check with nothing on the receipt saying so.",
        )
    if colours and text:
        # Echo the members as AUTHORED, not as re-rendered from the parsed RGB: the author has to
        # find these strings in the contract, and '#00FF00' is not '#00ff00' to a text search.
        written = _written_hex(question.enum)
        raise PromptCraftError(
            "CONTRACT_PALETTE_ENUM_MIXED",
            f"palette atom {question.atom_id!r} mixes hex colours {written} "
            f"with text member(s) {text}: no single instrument measures both",
            hint="The histogram measures hex colours; SigLIP2 screens text enums. A mixed enum "
            "would be measured over the hex half alone, so split it into two atoms -- one "
            "check_type=palette with the colours, one check_type=siglip2 with the words.",
        )
    return colours


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

    F-13f1ac97: ``Image.getdata()`` is deprecated and REMOVED in Pillow 14 (2027-10-15) -- Pillow's
    own call is ``deprecate("Image.Image.getdata", 14, "get_flattened_data")``, and its
    deprecate-for-two-majors policy puts the replacement's introduction at Pillow 12. This is a
    capability check rather than a rename because a rename would break the ``[image]`` extra's
    DECLARED ``pillow>=10.0`` floor: the attribute does not exist on 10.x or 11.x, and this repo's
    own norm is that a floor is a promise. Note the failure mode a rename-or-nothing choice was
    hiding: ``AttributeError`` is not ``ImportError``, so the removal would escape the guarded import
    above and ``PaletteVerifier.score`` would convert it into RUNTIME_VERIFIER_CALL_FAILED on EVERY
    palette atom -- a calendar-scheduled hard break of the only deterministic verifier in the domain.
    The other half of that fix is an upper bound on the dependency itself, which lives in
    pyproject.toml, not here.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return _load_png_filter0(path)
    _assert_png_not_short(path)
    im = Image.open(path).convert("RGB")
    flattened = getattr(im, "get_flattened_data", None)
    return list(flattened() if callable(flattened) else im.getdata())


def load_rgb_sized(path: str | Path) -> tuple[list[tuple[int, int, int]], int, int]:
    """``load_rgb`` plus the grid those pixels came from -- what a region crop needs.

    F-2c77d698. ``load_rgb`` returns a FLAT row-major list, which is everything ``_presence``
    needs and not enough to locate a rectangle inside. The size is read from the PNG's own IHDR
    (29 bytes, no decode) so this costs nothing on the branch that already read the file, and
    falls back to Pillow for the formats only Pillow reads.

    The two answers are cross-checked by ``crop_pixels``, which refuses when the decoded count
    disagrees with the declared size rather than cropping a rectangle out of the wrong grid --
    the same completeness discipline both readers above already apply.
    """
    pixels = load_rgb(path)
    width, height = image_size(path)
    return pixels, width, height


def image_size(path: str | Path) -> tuple[int, int]:
    """``(width, height)``, from the PNG header when possible and Pillow otherwise."""
    declared = _png_declared_size(path)
    if declared is not None:
        return declared
    try:
        from PIL import Image  # type: ignore
    except ImportError as err:
        raise PromptCraftError(
            "DEP_IMAGE_MISSING",
            f"reading the size of {path} needs Pillow (the stdlib reader handles PNG only)",
        ) from err
    with Image.open(path) as im:
        return (int(im.width), int(im.height))


def _png_declared_size(path: str | Path) -> tuple[int, int] | None:
    """Width/height off the IHDR, or None if this is not a PNG we can read a header from.

    Reads 33 bytes: the 8-byte signature plus the IHDR chunk's length/type/first-8-bytes. No
    decode, no allocation sized by a header field the caller controls (F-e9ad9f5d's lesson,
    applied to a function that only ever needs two integers).
    """
    try:
        with Path(path).open("rb") as fh:
            head = fh.read(33)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    if width <= 0 or height <= 0:
        return None
    return (int(width), int(height))


# IHDR colour type -> samples per pixel. Used only to size a scanline; the Pillow branch reads every
# real-world PNG, so this cannot be narrowed to the fallback's 8-bit-RGB-only case.
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}

# Pillow's own default MAX_IMAGE_PIXELS, hard-coded for the case where Pillow is absent or has had
# its bomb check disabled. Only ever used to decide "Pillow is about to refuse this anyway".
_DEFAULT_MAX_PIXELS = 89478485
# How much decompressed IDAT the guard holds at once. It COUNTS bytes, it never keeps the canvas.
_GUARD_CHUNK = 1 << 20


def _bomb_refusal_pixels() -> int:
    """The declared-canvas size at which Pillow itself refuses, so this guard can stop measuring.

    Read off the INSTALLED Pillow so the two guards draw the line in the same place. Note the
    factor of two, which is the whole subtlety: ``Image._decompression_bomb_check`` only WARNS above
    ``MAX_IMAGE_PIXELS`` and does not raise until ``2 * MAX_IMAGE_PIXELS``. MEASURED on Pillow
    12.2.0: a PNG declaring 10000x10000 (100,000,000 px, above the 89,478,485 warn threshold) is
    decoded normally with a DecompressionBombWarning. Capping this guard at the WARN threshold would
    therefore have opened a hole exactly where it is needed -- a short-IDAT file in that window would
    be padded with black by Pillow and scored, which is the F-09db27bc defect this guard exists to
    stop. Above the refusal threshold nothing gets scored at all, so declining to measure there
    costs nothing.

    ``Image.MAX_IMAGE_PIXELS`` may be set to None by an operator who deliberately disabled the bomb
    check; our own bound is not theirs to disable, so the default stands in.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return 2 * _DEFAULT_MAX_PIXELS
    limit = getattr(Image, "MAX_IMAGE_PIXELS", None)
    return 2 * (int(limit) if limit else _DEFAULT_MAX_PIXELS)


def _decompressed_length(idat: bytes, limit: int) -> int | None:
    """Bytes the IDAT decompresses to, counted (not kept) and stopped at ``limit``. None if corrupt.

    F-e9ad9f5d: this was ``zlib.decompressobj().decompress(idat)`` -- an unbounded allocation sized
    by the IHDR's declared width*height, a header field the caller controls. MEASURED with
    tracemalloc: a 291,662-byte PNG declaring 10000x10000 peaked at 587.8 MB here. The completeness
    question only needs a COUNT, never the pixels, so the stream is walked in ``_GUARD_CHUNK`` bites
    and only the running total is kept. That makes the guard O(1) in memory at any declared size,
    which is what lets it keep measuring everywhere Pillow would decode instead of standing down.
    """
    obj = zlib.decompressobj()
    produced = 0
    pending = idat
    try:
        while True:
            out = obj.decompress(pending, _GUARD_CHUNK)
            produced += len(out)
            # Whatever max_length held back stays here; empty means the input is fully consumed
            # AND fully emitted, so there is nothing left to count.
            pending = obj.unconsumed_tail
            if produced >= limit or not pending:
                return produced
    except zlib.error:
        return None


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

    F-e9ad9f5d: this ran BEFORE Pillow and decompressed with no bound, so the guard added to protect
    the shipped path DEFEATED Pillow's own O(1) decompression-bomb protection on that same path.
    MEASURED with tracemalloc: a 291,662-byte PNG declaring 10000x10000 (100,000,000 px, above
    Pillow's MAX_IMAGE_PIXELS of 89,478,485) peaked at 587.8 MB in 0.197s here and then returned
    WITHOUT refusing -- the IDAT is complete and the row count matches -- where Pillow alone refuses
    the identical file in 0.022s at 0.7 MB peak with DecompressionBombError. The end state through
    the front door was still that loud classified refusal, but only after an allocation sized by a
    header field the caller controls, and ``pcraft gate`` takes an operator-supplied image path.

    Two bounds now, because they answer different questions. The pixel cap decides whether to
    measure at all: above it the file is Pillow's problem, and returning None is already this
    function's documented "unmeasurable" contract. ``max_length`` bounds what an UNDER-cap file can
    make us allocate, since the IDAT could still decompress to far more than the IHDR promises --
    ``row_bytes * height`` is by definition everything needed to answer the completeness question,
    so stopping there loses nothing.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    width = height = bit = color = None
    # F-e9ad9f5d: was ``idat += chunk`` inside the walk loop -- quadratic in bytes copied for a PNG
    # with many small IDAT chunks. Accumulate, join once.
    idat_parts: list[bytes] = []
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
            idat_parts.append(chunk)
        elif typ == b"IEND":
            break
    # Unparseable (no IHDR, an unknown colour type / bit depth), or so large that Pillow is about to
    # refuse it outright -- in which case nothing downstream gets scored and there is nothing here
    # left to protect (F-e9ad9f5d).
    if (
        not width
        or not height
        or color not in _PNG_CHANNELS
        or bit not in (1, 2, 4, 8, 16)
        or width * height > _bomb_refusal_pixels()
    ):
        return None
    row_bytes = 1 + (width * bit * _PNG_CHANNELS[color] + 7) // 8
    # Counted, not kept, and stopped at the declared size: a truncated deflate stream must yield what
    # it has rather than raise, because "it has fewer rows than IHDR promised" IS the measurement.
    produced = _decompressed_length(b"".join(idat_parts), row_bytes * height)
    if produced is None:
        return None
    return (width, height, min(height, produced // row_bytes))


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
    idat_parts: list[bytes] = []  # F-e9ad9f5d: same quadratic accumulator as the sibling walker
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
            idat_parts.append(chunk)
        elif typ == b"IEND":
            break
    if width is None or height is None:
        raise PromptCraftError("RUNTIME_VERIFIER_CALL_FAILED", f"PNG {path} has no IHDR")
    raw = zlib.decompress(b"".join(idat_parts))
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
