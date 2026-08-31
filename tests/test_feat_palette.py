"""Palette histogram + reference lock. GPU-free."""

from __future__ import annotations

import struct
import sys
import types
import zlib
from pathlib import Path

import pytest

import pcraft.domains.image  # noqa: F401
from pcraft.core.contract.compile_questions import CheckType, Polarity, Question, Severity
from pcraft.core.plugin import get
from pcraft.domains.image.generator.reference_lock import assemble
from pcraft.domains.image.verifier import palette_verifier as pv
from pcraft.domains.image.verifier.palette_verifier import PaletteVerifier, Tier0Router
from pcraft.errors import PromptCraftError
from pcraft.testing import write_solid_png


def _q(enum: list[str]) -> Question:
    return Question(
        atom_id="palette",
        text="Does this match the palette?",
        check_type=CheckType.palette,
        polarity=Polarity.affirm,
        severity=Severity.required,
        enum=enum,
    )


def test_a_solid_palette_colour_is_present(tmp_path):
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    score = PaletteVerifier().score(str(path), _q(["#3a3a3a", "#d9d4c8", "#7a1f1f"]))
    assert score is not None
    assert score > 0.3  # ash-grey is present; the other two are not


def test_a_solid_off_palette_colour_is_near_zero(tmp_path):
    path = write_solid_png(tmp_path / "blue.png", (20, 40, 220))
    score = PaletteVerifier().score(str(path), _q(["#3a3a3a", "#d9d4c8", "#7a1f1f"]))
    assert score is not None
    assert score < 0.2


def test_text_enum_is_skipped_not_scored():
    v = PaletteVerifier()
    assert v.score("x.png", _q(["gold heraldry", "royal-blue heraldry"])) is None


def test_tier0_router_sends_palette_atoms_to_the_histogram(tmp_path):
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    router = Tier0Router()
    score = router.score(str(path), _q(["#3a3a3a"]))
    assert score == 1.0
    assert router.family == "siglip2"


def test_plugin_tier0_is_the_router():
    v0 = get("image").verifiers()[0]
    assert v0.verifier_id == "tier0.router.v1"
    assert v0.family == "siglip2"


# ==================================================== F-5ca8ecd3 (a score over a fraction of the image)
# The stdlib PNG fallback's row loop broke on the first empty slice and returned whatever it had;
# nothing compared len(pixels) against width*height. MEASURED: an IHDR declaring 10x10 (100 px) whose
# IDAT carried 2 rows decoded to 20 px with NO error raised, and _presence() produced a confident
# score from them. The receipt could not tell that from a full-image measurement. This path is a
# first-class supported configuration -- the verifier is advertised as "No model, no GPU".


def _png(width: int, height: int, rows: int, rgb=(58, 58, 58), interlace: int = 0) -> bytes:
    """A PNG whose IHDR declares width x height but whose IDAT carries only `rows` rows."""
    row = bytes([0]) + bytes(rgb) * width
    raw = row * rows

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, interlace))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _hide_pillow(monkeypatch) -> None:
    """Force the stdlib fallback: `from PIL import Image` raises ImportError when the entry is None."""
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)


def test_a_truncated_png_refuses_instead_of_decoding_a_fraction(tmp_path):
    path = tmp_path / "short.png"
    path.write_bytes(_png(10, 10, rows=2))
    with pytest.raises(PromptCraftError) as exc:
        pv._load_png_filter0(path)
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"
    assert "10x10" in exc.value.message
    assert "20" in exc.value.message  # says how many actually decoded


def test_score_over_a_truncated_png_is_a_refusal_not_a_number(monkeypatch, tmp_path):
    """The silent-wrongness shape: a normal float in [0,1] that the receipt cannot distinguish from
    a full-image measurement, in the one verifier that is supposed to be deterministic."""
    _hide_pillow(monkeypatch)
    path = tmp_path / "short.png"
    path.write_bytes(_png(10, 10, rows=2))
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(str(path), _q(["#3a3a3a"]))
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"


def test_a_complete_filter0_png_still_scores_through_the_stdlib_path(monkeypatch, tmp_path):
    """The completeness check must not break the configuration it protects."""
    _hide_pillow(monkeypatch)
    path = tmp_path / "full.png"
    path.write_bytes(_png(10, 10, rows=10))
    assert len(pv._load_png_filter0(path)) == 100
    assert PaletteVerifier().score(str(path), _q(["#3a3a3a"])) == 1.0


def test_an_interlaced_png_is_refused_rather_than_read_as_progressive_free(tmp_path):
    """The IHDR parse discarded the interlace byte into *_rest and never checked it, so an Adam7
    layout would have been decoded as if it were a plain row sequence."""
    path = tmp_path / "adam7.png"
    path.write_bytes(_png(10, 10, rows=10, interlace=1))
    with pytest.raises(PromptCraftError) as exc:
        pv._load_png_filter0(path)
    assert exc.value.code == "DEP_IMAGE_MISSING"
    assert "interlac" in exc.value.message.lower()


# ============================ F-f6646790 ("not installed" must not read as "checked and fine")
# load_rgb's try block spanned three statements: the PIL import, Image.open().convert('RGB'), and
# list(im.getdata()). Any ImportError raised from INSIDE Pillow during open/convert/decode (a lazy
# codec or plugin import failing) was misread as "Pillow is not installed" and silently rerouted to
# the stdlib filter-0 reader -- or, on a non-filter-0 file, reported DEP_IMAGE_MISSING "needs
# Pillow", a flatly wrong diagnosis that sends the operator to install a package they already have.


def _pillow_that_fails_at_decode(monkeypatch) -> None:
    fake_pil = types.ModuleType("PIL")
    fake_image = types.ModuleType("PIL.Image")

    def _open(_path):
        raise ImportError("cannot import name '_imaging' from 'PIL' (lazy codec)")

    fake_image.open = _open
    fake_pil.Image = fake_image
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image)


def test_a_decode_time_importerror_is_not_read_as_pillow_missing(monkeypatch, tmp_path):
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    _pillow_that_fails_at_decode(monkeypatch)
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(str(path), _q(["#3a3a3a"]))
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"
    assert isinstance(exc.value.cause, ImportError)
    assert "_imaging" in str(exc.value.cause)  # the REAL cause is attached, not swallowed


def test_a_genuinely_absent_pillow_still_falls_back_to_the_stdlib_reader(monkeypatch, tmp_path):
    """The narrowing must not remove the fallback -- only stop it from catching decode failures."""
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    _hide_pillow(monkeypatch)
    assert PaletteVerifier().score(str(path), _q(["#3a3a3a"])) == 1.0


# ================================== F-f68f59ff (the receipt must name the instrument that ran)


def test_the_router_names_the_delegate_that_actually_scored(tmp_path):
    """Every Tier-0 score was attributed to verifier_id='tier0.router.v1' family='siglip2',
    including ones produced by PaletteVerifier -- a deterministic stdlib RGB histogram whose own
    class declares family='palette-hist'. In a repo whose thesis is that receipts name what actually
    ran, the receipt named the wrong instrument."""
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    router = Tier0Router()
    assert router.last_delegate is None
    router.score(str(path), _q(["#3a3a3a"]))
    assert router.last_delegate is not None
    assert router.last_delegate["verifier_id"] == "palette.hist.v1"
    assert router.last_delegate["family"] == "palette-hist"


def test_a_text_enum_palette_atom_falls_through_to_siglip(tmp_path):
    """palette_verifier's own module docstring says text enums such as 'gold heraldry' are not
    colours and "those SKIP, they belong to SigLIP2" -- but the router routed on check_type alone
    and never fell through, so those atoms were skipped at Tier-0 entirely."""
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    router = Tier0Router()
    seen: list[str] = []

    class _Recorder:
        family = "siglip2"
        verifier_id = "siglip2.screen.v1"
        version = "so400m-patch14-384"

        def score(self, image_path, question):
            seen.append(question.atom_id)
            return 0.42

    router._siglip = _Recorder()
    score = router.score(str(path), _q(["gold heraldry", "royal-blue heraldry"]))
    assert seen == ["palette"], "the text-enum palette atom never reached SigLIP2"
    assert score == 0.42
    assert router.last_delegate["verifier_id"] == "siglip2.screen.v1"


def test_the_router_family_stays_siglip2_for_family_guard(tmp_path):
    """Pinned: family_guard sees ONE Tier-0 family. Naming the delegate on the receipt is the fix,
    not renaming the family out from under the guard."""
    router = Tier0Router()
    assert router.family == "siglip2"
    assert router.verifier_id == "tier0.router.v1"


def test_reference_lock_assembles_the_shipped_example():
    from pcraft.core.loop.orchestrate import _assemble_conditioning
    from pcraft.sample import load_sprite_example

    _s, resolved, _t, _c = load_sprite_example()
    lock = assemble(_assemble_conditioning(resolved))
    assert lock.pose and Path(lock.pose[0]).is_file()
    assert lock.identity and Path(lock.identity[0]).is_file()
    assert lock.costume and Path(lock.costume[0]).is_file()
