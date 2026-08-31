"""Palette histogram + reference lock. GPU-free."""

from __future__ import annotations

import importlib.util
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
