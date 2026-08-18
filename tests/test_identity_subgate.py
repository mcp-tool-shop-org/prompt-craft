"""The sprite identity sub-gate: measure, do not promote, do not delete.

Injectable similarity, no GPU. The Director ruled identity gates nothing.
This module computes CLIP-I cosine and routes failures to reference-anchored
inpaint. These tests record what it does; they do not decide whether it should.
"""

from __future__ import annotations

import pytest

from pcraft.core.gate.family_guard import assert_distinct_families, normalize_family
from pcraft.domains.image.subdomains.sprite import SpriteSubdomain
from pcraft.domains.image.subdomains.sprite.identity_subgate import IdentitySubGate
from pcraft.errors import PromptCraftError


def test_the_subdomain_factory_returns_the_same_object():
    """SpriteSubdomain.identity_subgate() was a factory nothing called."""
    g = SpriteSubdomain().identity_subgate(similarity=lambda _a, _b: 1.0)
    assert isinstance(g, IdentitySubGate)
    assert g.floor == 0.55


def test_defaults_are_hardcoded_and_unattributed():
    g = IdentitySubGate(similarity=lambda _a, _b: 1.0)
    assert g.floor == 0.55
    assert g.max_variance == 0.05


def test_a_constant_embedder_just_above_the_floor_passes():
    """The arm that does nothing: every view scores the same number.

    0.56 / variance 0 is inside the pass rectangle. A dead embedder that
    returns a constant above the floor looks identical to a perfect arm
    at these thresholds.
    """
    g = IdentitySubGate(similarity=lambda _a, _b: 0.56)
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png", "left": "l.png"})
    assert r is not None
    assert r.passed is True
    assert r.min_similarity == 0.56
    assert r.variance == 0.0


def test_a_perfect_match_also_passes():
    g = IdentitySubGate(similarity=lambda _a, _b: 1.0)
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png"})
    assert r is not None and r.passed is True
    assert r.min_similarity == 1.0


def test_just_under_the_floor_fails():
    """What this looks like if the floor is ignored: 0.549 would pass."""
    g = IdentitySubGate(similarity=lambda _a, _b: 0.549)
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png"})
    assert r is not None
    assert r.passed is False
    assert "floor" in r.reason


def test_one_drifted_view_fails_on_the_floor_not_the_variance():
    g = IdentitySubGate(
        similarity=lambda _a, b: {"f.png": 0.95, "b.png": 0.95, "l.png": 0.40}[b]
    )
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png", "left": "l.png"})
    assert r is not None
    assert r.passed is False
    assert r.min_similarity == 0.40


def test_variance_arm_does_not_fire_inside_the_floor_rectangle():
    """0.99 and 0.55 both clear the floor; variance is 0.0484, still under 0.05.

    The variance arm barely moves inside the pass rectangle. A palette
    shift that StyleID would call identity-drift can sit in this band.
    """
    g = IdentitySubGate(similarity=lambda _a, b: {"f.png": 0.99, "b.png": 0.55}[b])
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png"})
    assert r is not None
    assert r.min_similarity == 0.55
    assert r.passed is True
    assert r.variance <= 0.05


def test_unavailable_similarity_is_none_not_a_number():
    def missing(_a, _b):
        return None

    g = IdentitySubGate(similarity=missing)
    assert g.evaluate("plate.png", {"front": "f.png"}) is None


def test_family_is_siglip2_and_would_pass_a_diffusion_generator():
    """If this were wired through family_guard against SDXL it would pass.

    It is not wired. orchestrate only guards plugin.verifiers(). This
    sub-gate never enters that list. The family field is a label.
    """
    g = IdentitySubGate(similarity=lambda _a, _b: 1.0)
    assert normalize_family(g.family) == "siglip"
    assert_distinct_families("stable-diffusion", [g.family])


def test_family_would_refuse_a_siglip_generator_if_anyone_checked():
    g = IdentitySubGate(similarity=lambda _a, _b: 1.0)
    with pytest.raises(PromptCraftError) as exc:
        assert_distinct_families("siglip2", [g.family])
    assert exc.value.code == "GATE_SAME_FAMILY"
