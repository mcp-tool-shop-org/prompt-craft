from __future__ import annotations

import pytest

from pcraft.core.synth.assert_ import assert_coverage
from pcraft.core.synth.signature import TemplateSynthesizer
from pcraft.core.synth.visual_inventory import build_inventory, assert_tokens_trace
from pcraft.errors import PromptCraftError


def test_template_synth_every_token_traces_to_an_atom(sprite_example):
    _s, resolved, _t, compiled = sprite_example
    result = TemplateSynthesizer(compiled).synthesize(resolved, "")
    # the guard passes on the template's own output...
    assert_tokens_trace(result.prompt, result.visual_inventory)


def test_anti_prose_dump_guard_rejects_untraceable_tokens(sprite_example):
    _s, resolved, _t, _c = sprite_example
    inventory = build_inventory(resolved)
    polluted = "a grey-ash tabard worn over the torso, epic cinematic masterpiece trending on artstation"
    with pytest.raises(PromptCraftError) as exc:
        assert_tokens_trace(polluted, inventory)
    assert exc.value.code == "SYNTH_PROSE_DUMP"


def test_coverage_assert_passes_for_full_coverage(sprite_example):
    _s, resolved, _t, compiled = sprite_example
    result = TemplateSynthesizer(compiled).synthesize(resolved, "")
    assert_coverage(resolved, result.atom_coverage)  # no raise


def test_coverage_assert_flags_missing_required_atom(sprite_example):
    _s, resolved, _t, _c = sprite_example
    with pytest.raises(PromptCraftError) as exc:
        assert_coverage(resolved, {"tabard": "a tabard"})  # missing the rest
    assert exc.value.code == "SYNTH_COVERAGE_MISSING"


def test_coverage_assert_flags_unknown_atom(sprite_example):
    _s, resolved, _t, _c = sprite_example
    full = {a.id: a.claim for a in resolved.required_atoms()}
    full["ghost"] = "not a real atom"
    with pytest.raises(PromptCraftError) as exc:
        assert_coverage(resolved, full)
    assert exc.value.code == "SYNTH_COVERAGE_UNKNOWN_ATOM"
