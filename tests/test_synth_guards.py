from __future__ import annotations

import pytest

from pcraft.core.synth.assert_ import assert_coverage
from pcraft.core.synth.signature import TemplateSynthesizer
from pcraft.core.synth.visual_inventory import assert_tokens_trace, build_inventory
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


# ---------------------------------------------------------------------------
# F-27344f8e -- the missing-coverage refusal must say WHAT is uncovered
#
# The message named atom ids only ("2 required atom(s) have no coverage phrase:
# ['tabard', 'sigil']"), so a template-tuner staring at the refusal had to reopen the
# contract file to recall what 'tabard' actually claims. Its sibling guard in the same
# package -- assert_tokens_trace / SYNTH_PROSE_DUMP -- already names the offending
# content rather than a count, and this function is holding the resolved contract, so
# the claim text is one attribute away.
# ---------------------------------------------------------------------------


def test_the_missing_coverage_refusal_names_each_missing_atoms_claim(sprite_example):
    """The finding's own fixture: cover 'tabard' and nothing else, on the sprite example."""
    _s, resolved, _t, _c = sprite_example
    with pytest.raises(PromptCraftError) as exc:
        assert_coverage(resolved, {"tabard": "a tabard"})
    message = exc.value.message
    missing = [a for a in resolved.required_atoms() if a.id != "tabard"]
    assert len(missing) > 1, "fixture no longer leaves several required atoms uncovered"
    for atom in missing:
        assert atom.id in message  # what it always said...
        assert atom.claim in message  # ...and what needed a second file lookup


def test_the_missing_coverage_refusal_still_leads_with_the_count(sprite_example):
    """Collateral guard: the enrichment adds to the message, it does not replace the count
    a caller reads first to know how bad the miss is."""
    _s, resolved, _t, _c = sprite_example
    with pytest.raises(PromptCraftError) as exc:
        assert_coverage(resolved, {"tabard": "a tabard"})
    missing = [a for a in resolved.required_atoms() if a.id != "tabard"]
    assert exc.value.message.startswith(f"{len(missing)} required atom(s)")
    assert exc.value.code == "SYNTH_COVERAGE_MISSING"


def test_a_whitespace_only_coverage_phrase_is_still_missing(sprite_example):
    """The blank-is-missing rule the id list was already enforcing, kept explicit now that
    the message resolves claims: a phrase that is empty once stripped covers nothing."""
    _s, resolved, _t, _c = sprite_example
    coverage = {a.id: a.claim for a in resolved.required_atoms()}
    coverage["sigil"] = "   "
    with pytest.raises(PromptCraftError) as exc:
        assert_coverage(resolved, coverage)
    assert exc.value.code == "SYNTH_COVERAGE_MISSING"
    assert "sigil" in exc.value.message
    assert resolved.atom_by_id("sigil").claim in exc.value.message
