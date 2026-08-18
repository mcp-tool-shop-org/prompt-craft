"""Palette histogram + reference lock. GPU-free."""

from __future__ import annotations

from pathlib import Path

from pcraft.core.contract.compile_questions import CheckType, Polarity, Question, Severity
from pcraft.core.plugin import get
from pcraft.domains.image.generator.reference_lock import assemble
from pcraft.domains.image.verifier.palette_verifier import PaletteVerifier, Tier0Router
from pcraft.testing import write_solid_png

import pcraft.domains.image  # noqa: F401


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


def test_reference_lock_assembles_the_shipped_example():
    from pcraft.core.loop.orchestrate import _assemble_conditioning
    from pcraft.sample import load_sprite_example

    _s, resolved, _t, _c = load_sprite_example()
    lock = assemble(_assemble_conditioning(resolved))
    assert lock.pose and Path(lock.pose[0]).is_file()
    assert lock.identity and Path(lock.identity[0]).is_file()
    assert lock.costume and Path(lock.costume[0]).is_file()
