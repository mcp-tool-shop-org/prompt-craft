"""Palette histogram + reference lock. GPU-free."""

from __future__ import annotations

import importlib.util
import struct
import sys
import tracemalloc
import types
import zlib
from pathlib import Path

import pytest

import pcraft.domains.image  # noqa: F401
from pcraft.core.contract.compile_questions import CheckType, Polarity, Question, Severity
from pcraft.core.contract.schema import Spatial, SpatialKind
from pcraft.core.plugin import get
from pcraft.domains.image.generator.reference_lock import assemble
from pcraft.domains.image.verifier import palette_verifier as pv
from pcraft.domains.image.verifier.palette_verifier import PaletteVerifier, Tier0Router
from pcraft.errors import PromptCraftError
from pcraft.testing import write_solid_png

# The Pillow branch of load_rgb is what every [image]/GPU install runs. Its tests measure the REAL
# library, so they are skipped (not faked) on a bare [dev] install where Pillow is absent.
_HAS_PILLOW = importlib.util.find_spec("PIL") is not None
_needs_pillow = pytest.mark.skipif(not _HAS_PILLOW, reason="the Pillow branch needs Pillow installed")


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


# ================= F-09db27bc (the completeness check landed on the branch that does NOT ship)
# F-5ca8ecd3's declared-vs-decoded refusal was added to the stdlib fallback only -- the branch that
# runs when Pillow is ABSENT. The Pillow branch is the one every [image]/GPU install actually takes,
# and it got no equivalent guard. Where Pillow PADS rather than raises, the verifier scores a
# confident number over pixels Pillow invented. MEASURED with real Pillow: a PNG whose IHDR declares
# 10x10 but whose IDAT carries 2 rows returned 100 pixels with no error and scored 1.0 -- and because
# the padding colour is BLACK, a '#000000' atom scored 1.0 on an image containing zero black pixels.
# These run against whatever Pillow is installed; they are not fake-module tests.


@_needs_pillow
def test_the_pillow_branch_refuses_a_short_idat_png_like_the_fallback_does(tmp_path):
    """The primary shipped path must obey the same declared-vs-decoded law as the fallback."""
    path = tmp_path / "short.png"
    path.write_bytes(_png(10, 10, rows=2))
    with pytest.raises(PromptCraftError) as exc:
        pv.load_rgb(path)
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"
    assert "10x10" in exc.value.message
    assert "20" in exc.value.message  # says how many actually decoded


@_needs_pillow
def test_padding_black_may_not_satisfy_a_black_palette_atom(tmp_path):
    """The vivid shape: Pillow pads the missing rows with BLACK, so an enum asking for #000000 can be
    satisfied entirely by pixels that are not in the file. Zero of this image's real pixels are
    black; a score of 1.0 here is a measurement of Pillow's padding, not of the plate."""
    path = tmp_path / "short.png"
    path.write_bytes(_png(10, 10, rows=2, rgb=(200, 30, 30)))
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(str(path), _q(["#000000"]))
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"


@_needs_pillow
def test_the_two_readers_refuse_the_identical_bytes_with_the_identical_message(monkeypatch, tmp_path):
    """The asymmetry itself was the defect: the same file was a refusal on one branch and a
    confident 1.0 on the other. Pin that the two doors now speak with one voice."""
    path = tmp_path / "short.png"
    path.write_bytes(_png(10, 10, rows=2))
    with pytest.raises(PromptCraftError) as pillow_exc:
        pv.load_rgb(path)
    with monkeypatch.context() as m:
        _hide_pillow(m)
        with pytest.raises(PromptCraftError) as stdlib_exc:
            pv.load_rgb(path)
    assert pillow_exc.value.code == stdlib_exc.value.code
    assert pillow_exc.value.message == stdlib_exc.value.message


@_needs_pillow
def test_a_complete_png_still_scores_through_the_pillow_branch(tmp_path):
    """The guard must not break the configuration it protects -- this is the path production takes."""
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    assert PaletteVerifier().score(str(path), _q(["#3a3a3a"])) == 1.0
    complete = tmp_path / "full.png"
    complete.write_bytes(_png(10, 10, rows=10))
    assert len(pv.load_rgb(complete)) == 100


def test_a_non_png_is_not_refused_by_the_png_completeness_guard(tmp_path):
    """The guard is PNG-specific by construction. A format it cannot parse must fall through to
    Pillow untouched rather than become a false refusal -- load_rgb reads every real-world image."""
    assert pv._png_complete_rows(b"\xff\xd8\xff\xe0 not a png at all") is None
    assert pv._png_complete_rows(b"") is None


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


# ===================================== F-64b4f422 (a fix whose only readers were its own tests)
# F-f68f59ff added `last_delegate` and documented it as existing "so the receipt can say what ran".
# Nothing in src/ ever read it: harness.py stamps AtomVerdict.verifier_id from `verifier.verifier_id`
# -- the ROUTER's id -- and never consults a delegate attribute. Grep found exactly three
# occurrences (docstring, init, the write in _record) and the only readers were the tests above. So
# the original harm was verbatim intact on the receipt: MEASURED, harness.evaluate on a solid
# #7a1f1f plate with a check_type=palette atom produced verifier_id='tier0.router.v1', while
# last_delegate held palette.hist.v1 -- a name that appeared NOWHERE in the AtomVerdict JSON or the
# whole GateTranscript. These tests read the transcript, not the attribute, because asserting the
# field rather than the behaviour is what made the previous fix look live.


def _palette_transcript(tmp_path, sprite_example, enum=("#7a1f1f",)):
    from pcraft.core.contract.compile_questions import QuestionDAG
    from pcraft.core.gate import harness

    _s, _resolved, thresholds, _c = sprite_example
    path = write_solid_png(tmp_path / "sash.png", (122, 31, 31))
    dag = QuestionDAG(contract_id="char:test", questions=[_q(list(enum))])
    return harness.evaluate(
        dag, str(path), {0: Tier0Router()}, thresholds, generator_family="flux"
    )


def test_the_receipt_names_the_histogram_that_actually_scored_a_palette_atom(tmp_path, sprite_example):
    """The repo's thesis is that receipts name what actually ran. A deterministic no-model RGB
    histogram was being credited to the SigLIP2 neural family on every palette line."""
    transcript = _palette_transcript(tmp_path, sprite_example)
    verdict = transcript.verdicts[0]
    assert verdict.score == 1.0
    assert verdict.verifier_id == "palette.hist.v1"
    assert "palette.hist.v1" in transcript.model_dump_json(), "and it survives to the receipt JSON"


def test_a_siglip_scored_atom_is_still_attributed_to_siglip(tmp_path, sprite_example):
    """The other half: naming the delegate must not mean naming the histogram for everything. A
    text enum is not a colour, so it falls through to the screen -- and the receipt must say so."""
    from pcraft.core.contract.compile_questions import QuestionDAG
    from pcraft.core.gate import harness

    _s, _resolved, thresholds, _c = sprite_example
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))

    class _Recorder:
        family = "siglip2"
        verifier_id = "siglip2.screen.v1"
        version = "so400m-patch14-384"
        tier = 0

        def score(self, image_path, question):
            return 0.9

    router = Tier0Router()
    router._siglip = _Recorder()
    dag = QuestionDAG(contract_id="char:test", questions=[_q(["gold heraldry"])])
    transcript = harness.evaluate(
        dag, str(path), {0: router}, thresholds, generator_family="flux"
    )
    assert transcript.verdicts[0].verifier_id == "siglip2.screen.v1"


def test_the_router_id_is_what_a_fresh_router_reports(tmp_path):
    """Before anything has scored there is no delegate to name, so the router answers for itself --
    which is what the plugin smoke test and the tier registry read."""
    assert Tier0Router().verifier_id == "tier0.router.v1"


def test_reference_lock_buckets_a_reference_contract_by_scope(tmp_path):
    """Was test_reference_lock_assembles_the_shipped_example, which fed assemble() the SHIPPED
    contract -- both of whose plates declare method=ip_adapter, the SDXL encoder. Since F-0e41e735
    the lock refuses those by name rather than bucketing them (see the sibling test below), so the
    scope-bucketing property is measured on plates this recipe can actually apply."""
    plates = {
        scope: str(write_solid_png(tmp_path / f"{scope}.png"))
        for scope in ("face", "costume", "prop")
    }
    lock = assemble(
        {
            "pose_refs": [str(write_solid_png(tmp_path / "pose.openpose.png"))],
            "identity_refs": [
                {"plate": plate, "method": "reference", "scope": scope}
                for scope, plate in plates.items()
            ],
        }
    )
    assert lock.pose and Path(lock.pose[0]).is_file()
    assert lock.identity == [plates["face"]]
    assert lock.costume == [plates["costume"]]
    assert lock.extras == [plates["prop"]]


def test_reference_lock_refuses_the_shipped_examples_sdxl_method():
    """The shipped example is an SDXL contract: faction costume plate and character face plate both
    declare method=ip_adapter. The lock used to bucket them and hand build_graph the FACTION plate
    as the Kontext stitch identity, because _merge_identity_refs puts base refs first."""
    from pcraft.core.loop.orchestrate import _assemble_conditioning
    from pcraft.sample import load_sprite_example

    _s, resolved, _t, _c = load_sprite_example()
    with pytest.raises(PromptCraftError) as exc:
        assemble(_assemble_conditioning(resolved))
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "ip_adapter" in exc.value.message


# ============ F-00cfd3f8 (the router side: the receipt must name the BAND that judged the score)
# harness.evaluate zones on q.check_type.value, never on the delegate that produced the number,
# while Tier0Router.score deliberately routes a check_type=palette atom to SigLIP2 whenever the enum
# carries no hex colours. The two bands are not interchangeable and the shipped calibration says so:
# palette high=0.85/low=0.50, siglip2 high=0.10/low=0.01, with the note "siglip2 sigmoid is
# uncalibrated/pixel-art-tuned: >0.10 strong match, <0.01 absent". MEASURED end to end through the
# real harness with SigLIP2 stubbed: a text-enum palette atom scoring 0.30 -- three times that
# table's own strong-match threshold -- returned zone=FAIL, overall=FAIL, reason 'score 0.3000 ->
# FAIL', with 'palette' appearing nowhere in it. 0.12 -> FAIL, 0.60 -> UNCERTAIN; only >= 0.85
# passes, which the calibration says SigLIP2 does not produce.
#
# The harness half (zone under the instrument that scored) belongs to core/gate. THIS half is the
# router's contract with it: whoever produced the number must be nameable from the verdict, and the
# name must carry the band. The channel is verifier_id, and the convention is that a Tier-0
# delegate's id is "<band>.<instrument>.<version>" where <band> is a key in the shipped table.


def _band_of(verifier_id: str) -> str:
    """The convention harness-side zoning keys on. Deliberately spelled out here rather than
    imported, so the test breaks if the convention is quietly changed on either side."""
    return verifier_id.split(".", 1)[0]


def _real_siglip_scoring(value: float):
    """The REAL SigLIP2Screen with only its ENGINE stubbed -- no GPU, no ai-eyes import, and the
    class's own verifier_id/family/version rather than a stand-in's. A stub that hardcodes
    'siglip2.screen.v1' cannot prove the real screen's id is what reaches the verdict."""
    from pcraft.domains.image.verifier.siglip2_screen import SigLIP2Screen

    screen = SigLIP2Screen()
    screen._engine = types.SimpleNamespace(score=lambda image_path, text: value)
    return screen


def test_a_fall_through_verdict_carries_the_siglip2_family_verifier_id(tmp_path, sprite_example):
    """A palette atom whose enum names a colour by WORD is screened semantically. The verdict must
    name the screen, so band-aware zoning has something to key on."""
    from pcraft.core.contract.compile_questions import QuestionDAG
    from pcraft.core.gate import harness

    _s, _resolved, thresholds, _c = sprite_example
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    router = Tier0Router()
    router._siglip = _real_siglip_scoring(0.30)
    dag = QuestionDAG(contract_id="char:test", questions=[_q(["gold heraldry"])])
    transcript = harness.evaluate(dag, str(path), {0: router}, thresholds, generator_family="flux")
    verdict = transcript.verdicts[0]
    assert verdict.score == 0.30
    assert verdict.verifier_id == "siglip2.screen.v1"
    assert _band_of(verdict.verifier_id) == "siglip2", (
        "the fall-through verdict must carry the SigLIP2 FAMILY, not the atom's declared "
        "check_type -- this value is what instrument-aware zoning keys on"
    )
    assert router.band_key == "siglip2"


def test_a_native_palette_verdict_carries_the_histogram_verifier_id(tmp_path, sprite_example):
    """The other half: a real hex enum is measured by the deterministic histogram, and the verdict
    must keep naming the histogram's own band."""
    transcript = _palette_transcript(tmp_path, sprite_example)
    verdict = transcript.verdicts[0]
    assert verdict.verifier_id == "palette.hist.v1"
    assert _band_of(verdict.verifier_id) == "palette"


def test_every_tier0_delegate_id_names_a_band_in_the_shipped_table(sprite_example):
    """The convention is load-bearing, so pin it: every instrument the router can delegate to has a
    verifier_id whose first dotted segment is a real key in the shipped calibration table. A
    delegate whose id names no band would silently fall back to the table's `default`."""
    from pcraft.domains.image.verifier.siglip2_screen import SigLIP2Screen

    _s, _resolved, thresholds, _c = sprite_example
    for delegate in (PaletteVerifier, SigLIP2Screen):
        band = _band_of(delegate.verifier_id)
        assert band in thresholds.bands, (
            f"{delegate.__name__}.verifier_id={delegate.verifier_id!r} names band {band!r}, "
            f"which is not in the shipped table {sorted(thresholds.bands)}"
        )


def test_the_router_band_key_follows_the_delegate_not_the_check_type(tmp_path):
    """Both routes out of one check_type=palette atom, measured on the router itself: the hex enum
    stays on the palette band, the text enum moves to the siglip2 band. Zoning a fall-through on
    'palette' is the defect -- the shipped table puts 0.30 at FAIL there and PASS on siglip2."""
    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    router = Tier0Router()
    router._siglip = _real_siglip_scoring(0.30)
    router.score(str(path), _q(["#3a3a3a"]))
    assert router.band_key == "palette"
    router.score(str(path), _q(["gold heraldry"]))
    assert router.band_key == "siglip2"


# ================== F-411f3f58 (a one-character typo silently takes the atom off the instrument)
# _hex_colours discarded every enum member it could not parse with nothing recording the drop -- the
# F-916e73b6 defect class (silent drop of a declared constraint while the receipt still reads normal)
# landing on the enum field instead of the method field. MEASURED: ['#8B000'] parses 0/1,
# ['#8B00000'] 0/1, ['#gggggg'] 0/1, and the mixed ['#8B000','#8B0000'] parses 1/2 and scores over
# the survivor alone. Reachability is not hypothetical: the shipped example.faction.contract.json
# carries a check_type=palette atom whose enum is the hand-written hex ['#3a3a3a','#d9d4c8','#7a1f1f'].
#
# MEASURED end to end when EVERY member drops -- it is not an auto-pass, but it is never the
# measurement the contract asked for either. With SigLIP2 genuinely absent, enum=['#FF000'] on a pure
# red plate returned zone=SKIPPED / overall=UNAVAILABLE (verifier_id None, reason 'siglip2.screen.v1
# unavailable'); with SigLIP2 stubbed at 0.30 the same atom returned zone=FAIL / overall=FAIL, scored
# on the palette band. The identical plate with the correct ['#FF0000'] scores 1.0 PASS from
# palette.hist.v1. Nothing in either receipt names the typo.
#
# Fail closed the way refuse_unimplemented_identity does: a member that starts with '#' and does not
# yield a colour is an authoring error, refused BY NAME. A member with no '#' keeps the documented
# text-enum route to SigLIP2.


def test_a_five_digit_hex_is_refused_by_name_not_dropped(tmp_path):
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(str(path), _q(["#8B000"]))
    assert exc.value.code == "CONTRACT_PALETTE_ENUM_INVALID"
    assert "#8B000" in exc.value.message, "the refusal must name the offending member"


def test_a_seven_digit_hex_is_refused_by_name(tmp_path):
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(str(path), _q(["#8B00000"]))
    assert exc.value.code == "CONTRACT_PALETTE_ENUM_INVALID"


def test_a_non_hex_digit_body_is_refused_by_name(tmp_path):
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(str(path), _q(["#gggggg"]))
    assert exc.value.code == "CONTRACT_PALETTE_ENUM_INVALID"


def test_one_bad_member_refuses_rather_than_scoring_over_the_survivors(tmp_path):
    """MEASURED before the fix: ['#8B000','#8B0000'] parsed 1/2 and scored over the survivor alone,
    so the atom's declared check was narrowed by half with an ordinary float on the receipt."""
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(str(path), _q(["#8B000", "#8B0000"]))
    assert exc.value.code == "CONTRACT_PALETTE_ENUM_INVALID"
    assert "#8B000" in exc.value.message


def test_a_mixed_hex_and_text_enum_is_refused_as_unrepresentable(tmp_path):
    """The module docstring promises text enums "belong to SigLIP2", and that holds when EVERY
    member is text. MEASURED on ['#00FF00','gold heraldry']: the hex half was scored by the
    histogram (0.0) and the text half was dropped by both instruments -- it belonged to nobody."""
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(str(path), _q(["#00FF00", "gold heraldry"]))
    assert exc.value.code == "CONTRACT_PALETTE_ENUM_MIXED"
    assert "gold heraldry" in exc.value.message
    assert "#00FF00" in exc.value.message


def test_a_member_with_no_hash_keeps_the_documented_text_enum_route(tmp_path):
    """'8B0000' has no '#', so by the module's own rule it is a text enum, not a malformed colour.
    That route is unchanged: no colours parsed -> None -> the router screens it with SigLIP2."""
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    assert PaletteVerifier().score(str(path), _q(["8B0000"])) is None
    assert PaletteVerifier().score(str(path), _q(["gold heraldry"])) is None


def test_a_typo_hex_refuses_through_the_front_door_instead_of_reading_as_a_measurement(
    tmp_path, sprite_example
):
    """End to end. The same colour, one digit short, must not come back as an ordinary FAIL that a
    receipt cannot tell apart from an honest measurement."""
    from pcraft.core.contract.compile_questions import QuestionDAG
    from pcraft.core.gate import harness

    _s, _resolved, thresholds, _c = sprite_example
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    router = Tier0Router()
    router._siglip = _real_siglip_scoring(0.30)
    dag = QuestionDAG(contract_id="char:test", questions=[_q(["#FF000"])])
    with pytest.raises(PromptCraftError) as exc:
        harness.evaluate(dag, str(path), {0: router}, thresholds, generator_family="flux")
    assert exc.value.code == "CONTRACT_PALETTE_ENUM_INVALID"
    # ...and the correct spelling still measures, on the same plate.
    dag_ok = QuestionDAG(contract_id="char:test", questions=[_q(["#FF0000"])])
    ok = harness.evaluate(dag_ok, str(path), {0: router}, thresholds, generator_family="flux")
    assert ok.verdicts[0].score == 1.0


def test_the_shipped_faction_palette_enum_still_parses(sprite_example):
    """The guard must not break the configuration it protects: the shipped contract's palette atom
    is hand-written hex and has to keep going straight to the histogram."""
    _s, resolved, _t, _c = sprite_example
    enums = [list(a.enum) for a in resolved.must_have if a.enum]
    assert enums, "the shipped example should still carry an enum to measure"
    checked = 0
    for enum in enums:
        if any(str(m).startswith("#") for m in enum):
            colours, text, malformed = pv._split_enum(enum)
            assert not malformed, f"shipped enum {enum} would now be refused as malformed"
            assert not text, f"shipped enum {enum} would now be refused as mixed"
            assert colours
            checked += 1
    assert checked, "the shipped example should still carry a hex palette enum"


# ============================ F-13f1ac97 (a dated, calendar-scheduled break of the shipped reader)
# Image.getdata() is deprecated and REMOVED in Pillow 14 (2027-10-15); Pillow's own call is
# deprecate("Image.Image.getdata", 14, "get_flattened_data"), and its deprecate-for-two-majors policy
# puts the replacement's introduction at Pillow 12. A straight rename breaks the [image] extra's
# DECLARED pillow>=10.0 floor, because the attribute does not exist on 10.x or 11.x. AttributeError
# is not ImportError, so a removal would escape load_rgb's guarded import and surface as
# RUNTIME_VERIFIER_CALL_FAILED on EVERY palette atom. The migration is therefore a capability check,
# not a rename. (The upper bound on the dependency itself lives in pyproject.toml, which this domain
# does not own -- it is the other half of this fix.)


def _fake_pillow_with(monkeypatch, *, flattened: bool, legacy: bool) -> dict:
    calls: dict[str, int] = {"get_flattened_data": 0, "getdata": 0}

    class _Img:
        def convert(self, mode):
            return self

    if flattened:

        def _flattened(self):
            calls["get_flattened_data"] += 1
            return [(255, 0, 0)]

        _Img.get_flattened_data = _flattened
    if legacy:

        def _getdata(self):
            calls["getdata"] += 1
            return [(255, 0, 0)]

        _Img.getdata = _getdata

    fake_pil = types.ModuleType("PIL")
    fake_image = types.ModuleType("PIL.Image")
    fake_image.open = lambda _path: _Img()
    fake_pil.Image = fake_image
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image)
    return calls


def test_load_rgb_prefers_get_flattened_data_when_the_installed_pillow_has_it(monkeypatch, tmp_path):
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    calls = _fake_pillow_with(monkeypatch, flattened=True, legacy=True)
    assert pv.load_rgb(path) == [(255, 0, 0)]
    assert calls["get_flattened_data"] == 1
    assert calls["getdata"] == 0, "the deprecated call must not run when the replacement exists"


def test_load_rgb_still_works_on_a_pillow_that_predates_get_flattened_data(monkeypatch, tmp_path):
    """pillow 10.x / 11.x is inside the extra's DECLARED floor. A rename would AttributeError here,
    which is exactly why this is a capability check and not a rename."""
    path = write_solid_png(tmp_path / "red.png", (255, 0, 0))
    calls = _fake_pillow_with(monkeypatch, flattened=False, legacy=True)
    assert pv.load_rgb(path) == [(255, 0, 0)]
    assert calls["getdata"] == 1


@_needs_pillow
def test_the_installed_pillow_reads_a_plate_without_a_deprecation_warning(tmp_path):
    """Against whatever Pillow is actually installed -- not a fake. There is no filterwarnings
    setting in pyproject.toml, so the deprecated call was emitted once per load_rgb into every
    suite run."""
    import warnings

    path = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert pv.load_rgb(path)
    offenders = [str(w.message) for w in caught if "getdata" in str(w.message)]
    assert not offenders, offenders


# ================== F-e9ad9f5d (the guard added to stop a bomb IS the bomb on the path it guards)
# _assert_png_not_short runs BEFORE Pillow and decompresses with no bound, so it defeats Pillow's own
# O(1) decompression-bomb protection on the exact path it was added to protect. MEASURED with
# tracemalloc on this rig: a 291,662-byte PNG declaring 10000x10000 (100,000,000 px, above Pillow's
# MAX_IMAGE_PIXELS of 89,478,485) made _png_complete_rows peak at 587.8 MB in 0.197s and then return
# (10000, 10000, 10000) -- i.e. it did NOT refuse, because the IDAT is complete. The allocation scales
# linearly with a number in the header, and `pcraft gate` takes an operator-supplied image path.


def _bomb_png(width: int, height: int) -> bytes:
    """A PNG whose IHDR declares a huge canvas and whose IDAT really does carry every row.
    Streamed through compressobj so building it never materialises the raw scanlines."""
    row = bytes(1 + width * 3)
    co = zlib.compressobj(9)
    parts = [co.compress(row) for _ in range(height)]
    parts.append(co.flush())
    idat = b"".join(parts)

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def test_a_bomb_shaped_png_is_measured_without_a_large_allocation():
    """MEASURED before the fix: this exact input peaked at 587.8 MB. The completeness question only
    ever needed a byte COUNT, so the guard must answer it without materialising the canvas -- and it
    must still answer it, because Pillow decodes a file this size (it is above the WARN threshold,
    below the refusal one) and would pad a short IDAT with black."""
    data = _bomb_png(10000, 10000)
    assert len(data) < 1_000_000, "the input really is small; the allocation was not"
    tracemalloc.start()
    try:
        measured = pv._png_complete_rows(data)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert measured == (10000, 10000, 10000), "a complete bomb-shaped PNG is complete, not short"
    assert peak < 64 * 1024 * 1024, f"peaked at {peak / 1048576:.1f} MB on a {len(data)}-byte input"


def test_a_short_idat_is_still_caught_in_pillows_warn_window():
    """The hole a naive cap would have opened. 10000x10000 is above Pillow's MAX_IMAGE_PIXELS but
    below the 2x threshold at which it RAISES, so Pillow decodes the file and pads the missing rows
    with black -- the F-09db27bc defect. Standing down here would have handed that back."""
    data = _bomb_png(10000, 10000)
    truncated = data[: len(data) // 2]
    measured = pv._png_complete_rows(truncated)
    assert measured is not None, "this file is measurable and it is short"
    width, height, rows = measured
    assert (width, height) == (10000, 10000)
    assert rows < height


def test_a_png_past_pillows_refusal_threshold_is_left_to_pillow(tmp_path):
    """Above 2 * MAX_IMAGE_PIXELS Pillow raises DecompressionBombError, so nothing downstream is
    ever scored and there is nothing here left to protect. Returning None is already the documented
    'unmeasurable' contract, and a false refusal would break the path this guard exists to protect."""
    data = _bomb_png(20000, 10000)  # 200,000,000 px > 2 * 89,478,485
    assert pv._png_complete_rows(data) is None
    path = tmp_path / "bomb.png"
    path.write_bytes(data)
    pv._assert_png_not_short(path)  # must not raise; Pillow gets to speak


def test_the_guard_stands_down_exactly_where_pillow_refuses():
    """Both guards have to draw the line in the same place. The factor of two is the subtlety:
    _decompression_bomb_check only WARNS above MAX_IMAGE_PIXELS and does not raise until twice it."""
    assert pv._bomb_refusal_pixels() > 0
    if _HAS_PILLOW:
        from PIL import Image

        assert pv._bomb_refusal_pixels() == 2 * Image.MAX_IMAGE_PIXELS


def test_an_under_cap_short_png_is_still_refused():
    """The cap must not swallow the refusal it was added around."""
    assert pv._png_complete_rows(_png(10, 10, rows=2)) == (10, 10, 2)


def test_many_small_idat_chunks_still_parse():
    """The IDAT accumulator was `idat += chunk` inside the walk loop -- quadratic in bytes copied
    for a PNG with many small IDAT chunks. Joining once must not change what is parsed."""

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = (bytes([0]) + bytes((58, 58, 58)) * 10) * 10
    blob = zlib.compress(raw, 9)
    pieces = [blob[i : i + 3] for i in range(0, len(blob), 3)]
    assert len(pieces) > 3, "the point is MANY chunks"
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0))
        + b"".join(chunk(b"IDAT", p) for p in pieces)
        + chunk(b"IEND", b"")
    )
    assert pv._png_complete_rows(data) == (10, 10, 10)


# ================================================================ F-2c77d698 (region-localized)
# `Atom.spatial` with kind=region is documented in core/contract/schema.py as "a named image region
# (torso, head, hands, chest-center)" and "a CHECKABLE image region" -- and MEASURED across src/,
# nothing checked it: compile_questions copies it onto the Question, loader uses it for the
# no-relaxation comparison, orchestrate reads it only to pick an INPAINT region, and ZERO verifier
# modules referenced `question.spatial` at all. So the shipped `sigil` atom (spatial region=
# chest-center) was answered from anywhere in the frame: a sigil painted on the shoulder satisfied
# chest-center. The window is computable GPU-free -- `conditioning.region_box` already returns the
# exact pixel box, and it is the SAME function the inpaint repair uses, so the window the gate
# checks is the window the repair paints.
#
# THE HONEST FIRST TARGET is the deterministic histogram. The three model-backed verifiers keep
# scoring the full frame until a region calibration is measured for them, and they SAY SO rather
# than partially honouring the field in silence.


def _grid_png(path, rows: list[list[tuple[int, int, int]]]):
    """A PNG with arbitrary per-pixel colours -- write_solid_png cannot express a region."""
    height = len(rows)
    width = len(rows[0])
    raw = b"".join(bytes([0]) + b"".join(bytes(px) for px in row) for row in rows)

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    blob = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
    return p


_ASH = (58, 58, 58)  # #3a3a3a
_WHITE = (255, 255, 255)  # #ffffff -- the sigil colour


def _sigil_on_the_shoulder(path, size: int = 64):
    """The finding's own example, as pixels: a white patch high-left, nothing in chest-center.

    100 white pixels out of 4096 is 2.4% of the frame -- six times _MIN_FRAC -- so the FULL-FRAME
    histogram calls the colour present. `region_box(64, 64, 'chest-center')` is (9, 19, 54, 44),
    which the patch (rows 0-9, cols 0-9) does not touch at all.
    """
    rows = [[_ASH for _ in range(size)] for _ in range(size)]
    for y in range(10):
        for x in range(10):
            rows[y][x] = _WHITE
    return _grid_png(path, rows)


def _region_q(region: str, enum: list[str] | None, kind: str = "region") -> Question:
    return Question(
        atom_id="sigil",
        text="Does this image show a white triple-bar sigil on the tabard?",
        check_type=CheckType.palette,
        polarity=Polarity.affirm,
        severity=Severity.required,
        spatial=Spatial(kind=SpatialKind(kind), ref=region),
        enum=enum,
    )


def test_a_region_atom_is_scored_over_its_region_not_the_whole_frame(tmp_path):
    """The defect, as one pair of numbers: the same plate, the same enum, the same verifier."""
    path = str(_sigil_on_the_shoulder(tmp_path / "shoulder.png"))
    whole_frame = PaletteVerifier().score(path, _q(["#ffffff"]))
    assert whole_frame == pytest.approx(1.0), "the colour IS in the frame -- just not where declared"
    in_region = PaletteVerifier().score(path, _region_q("chest-center", ["#ffffff"]))
    assert in_region == pytest.approx(0.0), "a sigil on the shoulder does not satisfy chest-center"


def test_an_atom_with_no_spatial_is_scored_exactly_as_before(tmp_path):
    """MUST NOT BREAK. `_presence` measures a fraction of TOTAL pixels against _MIN_FRAC, so a crop
    changes what 'present' MEANS. The shipped palette atom carries no spatial, so it must not move:
    the crop is gated on the field being present, and the receipt says which window was scored."""
    ash = write_solid_png(tmp_path / "ash.png", _ASH)
    v = PaletteVerifier()
    assert v.score(str(ash), _q(["#3a3a3a", "#d9d4c8", "#7a1f1f"])) == pytest.approx(0.3333)
    assert v.verifier_id_for(_q(["#3a3a3a"])) == "palette.hist.v1", "the full-frame id does not move"
    assert v.last_region is None
    assert "region" not in (v.breakdown_detail() or "")


def test_a_pose_spatial_is_not_a_region_and_never_crops(tmp_path):
    """kind=pose names a ControlNet guide image, not a checkable window. The shipped `weapon` atom
    carries one, and cropping to a filename would be nonsense -- it is a documented no-op."""
    path = str(_sigil_on_the_shoulder(tmp_path / "shoulder.png"))
    q = _region_q("poses/two-hand-weapon.openpose.png", ["#ffffff"], kind="pose")
    v = PaletteVerifier()
    assert v.score(path, q) == pytest.approx(1.0), "scored full-frame, exactly as before"
    assert v.last_region is None
    assert v.verifier_id_for(q) == "palette.hist.v1"


def test_an_unrecognised_region_is_refused_by_name_not_scored_on_a_guessed_window(tmp_path):
    """Region names are contract-authored free text and `region_box` silently returns a CENTRE box
    for anything it does not recognise -- so an atom declaring `shouldre` would have been scored on
    a window nobody asked for, and the receipt would have read like an ordinary verdict. Same
    discipline as conditioning._SUPPORTED_METHODS: a name nobody wired is refused BY NAME."""
    path = str(_sigil_on_the_shoulder(tmp_path / "shoulder.png"))
    with pytest.raises(PromptCraftError) as exc:
        PaletteVerifier().score(path, _region_q("shouldre", ["#ffffff"]))
    assert exc.value.code == "CONTRACT_SPATIAL_REGION_UNKNOWN"
    assert "shouldre" in exc.value.message
    assert "sigil" in exc.value.message, "name the atom the author has to go and edit"
    hint = exc.value.hint or ""
    assert "chest-center" in hint, "the refusal lists the windows that DO exist"


def test_the_region_delegate_moves_the_version_and_never_the_band(tmp_path):
    """A score from a crop is NOT on the full-frame scale, so it may not be stamped with the id of
    the instrument that produced full-frame numbers -- that is the silent re-decide
    STATE_REPLAY_DRIFT exists to make visible. The '<band>.<instrument>.<version>' convention is
    load-bearing: the band segment must not move (harness._band_key keys zoning on it), only the
    version."""
    v = PaletteVerifier()
    region_id = v.verifier_id_for(_region_q("chest-center", ["#ffffff"]))
    assert region_id != v.verifier_id_for(_q(["#ffffff"])), "one id for two scales is the defect"
    assert region_id.split(".")[0] == "palette", "the band segment is what zoning reads"
    assert region_id == "palette.hist.v2"
    assert v.version_for(_region_q("chest-center", ["#ffffff"])) == "v2"


def test_the_router_reports_the_region_delegate_and_keeps_the_band(tmp_path):
    path = str(_sigil_on_the_shoulder(tmp_path / "shoulder.png"))
    router = Tier0Router()
    router.score(path, _region_q("chest-center", ["#ffffff"]))
    assert router.last_delegate["verifier_id"] == "palette.hist.v2"
    assert router.last_delegate["family"] == "palette-hist"
    assert router.verifier_id == "palette.hist.v2"
    assert router.band_key == "palette", "zoning must not silently fall through to `default`"


def test_the_receipt_says_which_box_was_scored(tmp_path, sprite_example):
    """Route the crop through the existing detail seam (harness._detail_for) so a verdict scored
    over a region SAYS so. A cropped number sitting on a full-frame line with nothing distinguishing
    it is the whole hazard."""
    from pcraft.core.contract.compile_questions import QuestionDAG
    from pcraft.core.gate import harness

    _s, _resolved, thresholds, _c = sprite_example
    path = str(_sigil_on_the_shoulder(tmp_path / "shoulder.png"))
    dag = QuestionDAG(contract_id="char:test", questions=[_region_q("chest-center", ["#ffffff"])])
    transcript = harness.evaluate(
        dag, path, {0: Tier0Router()}, thresholds, generator_family="flux"
    )
    verdict = transcript.verdicts[0]
    assert verdict.verifier_id == "palette.hist.v2"
    assert verdict.band_key == "palette"
    detail = verdict.detail or ""
    assert "chest-center" in detail, "the receipt names the region the contract declared"
    assert "(9, 19, 54, 44)" in detail, "and the pixel box that was actually measured"
    assert "palette.hist.v2" in transcript.model_dump_json()


def test_the_gate_window_is_the_same_function_the_repair_paints(tmp_path):
    """`orchestrate` hands the same region name to `conditioning.region_box` to pick the INPAINT
    box. Deriving the gate's window from a second copy would let the two drift, so the checked
    window and the repainted window are one function."""
    from pcraft.domains.image.generator.conditioning import region_box
    from pcraft.domains.image.verifier.region import region_window

    for name in ("head", "torso", "chest-center", "hands", "fist"):
        assert region_window(64, 64, name, atom_id="a") == region_box(64, 64, name)


def test_the_model_backed_verifiers_say_they_scored_the_full_frame(tmp_path):
    """Refusal of scope, on the receipt rather than only in a comment. VQAScore / SigLIP2 hand the
    full-frame path straight to their model, and cropping would move them onto an unmeasured scale
    -- so the honest state is 'still full-frame, and the transcript says which atoms that cost'."""
    from pcraft.domains.image.verifier.siglip2_screen import SigLIP2Screen
    from pcraft.domains.image.verifier.vqascore_verifier import VQAScoreVerifier

    region = _region_q("chest-center", None)
    for verifier in (SigLIP2Screen(), VQAScoreVerifier()):
        note = verifier.score_detail("x.png", region)
        assert note, f"{verifier.verifier_id} silently ignored a declared region"
        assert "chest-center" in note
        assert "full frame" in note.lower()
        assert verifier.score_detail("x.png", _q(["#ffffff"])) is None, "no region, nothing to say"


def test_the_router_carries_the_screens_full_frame_note_too(tmp_path):
    """The harness asks the DECIDING instrument, which for a Tier-0 siglip2 atom is the router. A
    note the router swallows is a note nobody reads."""
    path = str(_sigil_on_the_shoulder(tmp_path / "shoulder.png"))
    router = Tier0Router()

    class _Recorder:
        family = "siglip2"
        verifier_id = "siglip2.screen.v1"
        version = "so400m-patch14-384"
        tier = 0

        def score(self, image_path, question):
            return 0.5

        def score_detail(self, image_path, question):
            from pcraft.domains.image.verifier.region import full_frame_note

            return full_frame_note(question, self.verifier_id)

    router._siglip = _Recorder()
    q = _region_q("chest-center", ["gold heraldry"])
    router.score(path, q)
    detail = router.score_detail(path, q)
    assert detail and "chest-center" in detail and "full frame" in detail.lower()
