from __future__ import annotations

import pytest

from pcraft.core.gate.family_guard import assert_distinct_families, normalize_family
from pcraft.core.gate.verifier_iface import forbid_clipscore
from pcraft.errors import PromptCraftError


def test_siglip2_siblings_normalize_to_one_family():
    assert normalize_family("google/siglip2-so400m-patch14-384") == "siglip"
    assert normalize_family("google/siglip2-so400m-patch16-512") == "siglip"


def test_same_family_generator_and_verifier_is_refused():
    with pytest.raises(PromptCraftError) as exc:
        assert_distinct_families("stable-diffusion", ["clip-flant5", "stable-diffusion"])
    assert exc.value.code == "GATE_SAME_FAMILY"


def test_distinct_families_pass():
    assert_distinct_families("stable-diffusion", ["siglip", "clip-flant5", "dsg-qg"])  # no raise


def test_a_generative_vlm_may_score_a_diffusion_image():
    """Rule (2): different family. Not a blanket ban on generative verifiers."""
    assert_distinct_families("stable-diffusion", ["llava", "qwen-vl"])


def test_two_generative_vlms_share_a_family_token_today():
    """LLaVA generating and Qwen-VL scoring both normalize to generative-vlm."""
    with pytest.raises(PromptCraftError) as exc:
        assert_distinct_families("llava", ["qwen-vl"])
    assert exc.value.code == "GATE_SAME_FAMILY"
    assert normalize_family("llava") == normalize_family("qwen-vl") == "generative-vlm"


def test_clipscore_is_banned_as_gate_metric():
    class _ClipScore:
        verifier_id = "clipscore.v0"
        version = "v0"
        family = "clipscore"
        tier = 1

        def score(self, image_path, question):
            return 0.5

    with pytest.raises(PromptCraftError) as exc:
        forbid_clipscore(_ClipScore())
    assert exc.value.code == "GATE_CLIPSCORE_BANNED"
