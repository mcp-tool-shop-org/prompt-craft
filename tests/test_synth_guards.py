from __future__ import annotations

import pytest

from pcraft.core.synth.assert_ import assert_coverage
from pcraft.core.synth.signature import TemplateSynthesizer
from pcraft.core.synth.visual_inventory import (
    RENDER_BOILERPLATE,
    assert_tokens_trace,
    build_inventory,
)
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


# ---------------------------------------------------------------------------
# F-c6b06c2f -- `encoder_rules` is accepted and never read
#
# MEASURED in core/synth/signature.py: TemplateSynthesizer.synthesize(resolved,
# encoder_rules, *, boost_ids) builds its prompt from build_inventory(resolved) plus the
# module-level RENDER_BOILERPLATE constant; `encoder_rules` never appears in the body. The
# five boilerplate tokens ("full body visible", "front-facing view", "isolated on plain
# white background", "character concept art", "clean sharp lines") are sprite/image-specific
# phrasing defined at domain-agnostic module scope, so a video or audio domain would carry
# them too -- and it has no "background" to isolate anything on.
#
# The fix moves the SOURCE of those tokens, not their status: boilerplate stays outside the
# contract schema, and stays inside assert_tokens_trace's allow-list mechanism. What changes
# is that a DomainPlugin's encoder-rules file can declare its own, in a marked block. Rules
# that declare no block -- which is every shipped rules file today, and the "" the tests in
# this module pass -- fall back to RENDER_BOILERPLATE, byte for byte.
# ---------------------------------------------------------------------------

_RULES_WITH_BOILERPLATE = """
# some domain rules

<!-- pcraft:render_boilerplate -->
- stereo field centered
- 48 kHz master
<!-- /pcraft:render_boilerplate -->

more prose after the block
"""

_RULES_DECLARING_NONE = """
<!-- pcraft:render_boilerplate -->
<!-- /pcraft:render_boilerplate -->
"""


def test_empty_encoder_rules_still_produce_the_shipped_boilerplate(sprite_example):
    """The byte-for-byte guarantee: every existing caller passes "" or a rules file with no
    block, and its prompt must not move."""
    _s, resolved, _t, compiled = sprite_example
    result = TemplateSynthesizer(compiled).synthesize(resolved, "")
    for token in RENDER_BOILERPLATE:
        assert token in result.prompt
    assert result.prompt.endswith(RENDER_BOILERPLATE[-1])


def test_the_shipped_rules_file_changes_nothing_because_it_declares_no_block(sprite_example):
    """The image domain's generated encoder_craft.md carries no boilerplate block, so
    threading the parameter must leave its output identical to the ""-passing call."""
    from pcraft.sample import _encoder_rules

    _s, resolved, _t, compiled = sprite_example
    synth = TemplateSynthesizer(compiled)
    assert synth.synthesize(resolved, _encoder_rules()).prompt == synth.synthesize(
        resolved, ""
    ).prompt


def test_domain_declared_boilerplate_replaces_the_image_specific_default(sprite_example):
    from pcraft.core.synth.visual_inventory import parse_render_boilerplate

    _s, resolved, _t, compiled = sprite_example
    result = TemplateSynthesizer(compiled).synthesize(resolved, _RULES_WITH_BOILERPLATE)
    assert result.prompt.endswith("stereo field centered, 48 kHz master")
    assert "isolated on plain white background" not in result.prompt
    assert parse_render_boilerplate(_RULES_WITH_BOILERPLATE) == [
        "stereo field centered",
        "48 kHz master",
    ]


def test_a_domain_may_declare_that_it_has_no_boilerplate_at_all(sprite_example):
    """A PRESENT but empty block is a decision; an ABSENT block is silence. The finding's own
    example -- a domain with no 'background' concept -- needs the first to be expressible."""
    from pcraft.core.synth.visual_inventory import parse_render_boilerplate

    _s, resolved, _t, compiled = sprite_example
    assert parse_render_boilerplate(_RULES_DECLARING_NONE) == []
    prompt = TemplateSynthesizer(compiled).synthesize(resolved, _RULES_DECLARING_NONE).prompt
    for token in RENDER_BOILERPLATE:
        assert token not in prompt
    assert prompt  # the atoms are still there


def test_absent_and_empty_rules_both_fall_back_to_the_literal_default():
    from pcraft.core.synth.visual_inventory import parse_render_boilerplate

    assert parse_render_boilerplate("") == RENDER_BOILERPLATE
    assert parse_render_boilerplate(None) == RENDER_BOILERPLATE
    assert parse_render_boilerplate("# rules with no block\n") == RENDER_BOILERPLATE


def test_the_parsed_list_is_a_copy_the_caller_cannot_mutate_the_default_through():
    from pcraft.core.synth.visual_inventory import parse_render_boilerplate

    parsed = parse_render_boilerplate("")
    parsed.append("trending on artstation")
    assert "trending on artstation" not in RENDER_BOILERPLATE


def test_domain_boilerplate_does_not_bypass_the_prose_dump_guard(sprite_example):
    """The hard must-not. Boilerplate is still allow-listed rather than exempt: the guard
    admits it only when TOLD the domain's list, and refuses it under the default list."""
    _s, resolved, _t, compiled = sprite_example
    result = TemplateSynthesizer(compiled).synthesize(resolved, _RULES_WITH_BOILERPLATE)
    inventory = build_inventory(resolved)

    with pytest.raises(PromptCraftError) as exc:
        assert_tokens_trace(result.prompt, inventory)  # default allow-list: image boilerplate
    assert exc.value.code == "SYNTH_PROSE_DUMP"
    assert "48 kHz master" in exc.value.message

    from pcraft.core.synth.visual_inventory import parse_render_boilerplate

    assert_tokens_trace(
        result.prompt, inventory, boilerplate=parse_render_boilerplate(_RULES_WITH_BOILERPLATE)
    )


def test_a_prose_dump_is_still_refused_under_a_domain_allow_list(sprite_example):
    """Widening the allow-list must not widen it to everything."""
    _s, resolved, _t, _c = sprite_example
    with pytest.raises(PromptCraftError) as exc:
        assert_tokens_trace(
            "a grey-ash tabard worn over the torso, epic cinematic masterpiece 8k",
            build_inventory(resolved),
            boilerplate=["stereo field centered"],
        )
    assert exc.value.code == "SYNTH_PROSE_DUMP"


def test_the_boilerplate_block_never_becomes_a_contract_atom(sprite_example):
    """visual_inventory's own rule: do NOT turn 'front-facing view' / 'plain white background'
    into atoms. Domain-supplied tokens inherit that rule -- only the SOURCE moved."""
    _s, resolved, _t, compiled = sprite_example
    result = TemplateSynthesizer(compiled).synthesize(resolved, _RULES_WITH_BOILERPLATE)
    assert [r.atom_id for r in result.visual_inventory] == [a.id for a in resolved.must_have]
    assert "stereo field centered" not in result.atom_coverage.values()


def test_the_template_synthesizer_stays_gpu_free_and_network_free(sprite_example):
    """The parameter is read from a string, not fetched. Same synthesizer_id, same backend."""
    _s, resolved, _t, compiled = sprite_example
    synth = TemplateSynthesizer(compiled)
    before = synth.synthesizer_id
    result = synth.synthesize(resolved, _RULES_WITH_BOILERPLATE)
    assert synth.synthesizer_id == before
    assert result.backend == "template"
    assert result.degraded is False
