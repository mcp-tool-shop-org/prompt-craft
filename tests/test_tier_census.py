"""N of M required tiers executed — independent of the verdict."""

from __future__ import annotations

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.gate import harness
from pcraft.core.gate.thresholds import Zone
from pcraft.testing import ScriptedVerifier


def test_watchdog_counts_required_tiers_not_the_verdict(sprite_example):
    """⚑ REWRITTEN IN PLACE (amend wave 2, F-175c3b3e / F-d9b28ca6).

    This used to assert "A PASS that never ran Tier-0 is still a PASS, and the census says
    1 of 2" — i.e. it PINNED the hole: ``_pick`` fell forward from the missing Tier-0 onto the
    registered Tier-1 verifier, the fabricated score got graded against the palette band anyway,
    and the resulting PASS was the exact reason ``pcraft demo`` could print a green BOUND over a
    gate that only ran half its instruments. That was a bug wearing a test, not a spec.

    ``_pick`` no longer falls forward across tiers (F-175c3b3e): a required atom whose own tier
    never registered a verifier is SKIPPED, not silently scored on someone else's calibration.
    A SKIPPED required atom never rolls up to PASS (``_rollup``) — so the zone and the census
    now tell the SAME honest story instead of disagreeing. The census number is UNCHANGED (still
    1 of 2, because Tier-1's five other required atoms score fine) — what changed is that the
    verdict finally agrees with it, and the two facts are asserted here side by side, independent
    of each other, exactly as ``TierCensus``'s docstring says they must be.
    """
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier()  # only tier 1 registered; Tier-0 (palette) no longer falls forward onto it
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["palette"].zone is Zone.SKIPPED  # Tier-0 never ran; not graded on Tier-1's scale
    assert t.overall is Zone.UNCERTAIN  # no longer a silent PASS
    # The two facts stay separate (not folded into one another): the zone says UNCERTAIN on its
    # own merits (a required atom SKIPped); the census independently still says 1 of 2.
    assert t.tier_census.required == [0, 1]
    assert t.tier_census.executed == [1]
    assert t.tier_census.n == 1
    assert t.tier_census.m == 2


def test_watchdog_is_zero_of_m_when_nothing_scored(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: None)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert t.tier_census.n == 0
    assert t.tier_census.m == 2
    assert t.tier_census.executed == []


def test_watchdog_does_not_credit_an_unrequired_escalation_tier(sprite_example):
    """Tier 2 is escalation. Scoring on T1 does not list 2 as required."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t1 = ScriptedVerifier()
    t2 = ScriptedVerifier(family="dsg-qg", tier=2, verifier_id="scripted.dsg.v0")
    t = harness.evaluate(dag, "x.png", {1: t1, 2: t2}, thresholds, generator_family="stable-diffusion")
    assert 2 not in t.tier_census.required
    assert t.tier_census.executed == [1]


# --------------------------------------------------------------------------------------------
# F-6acc1597 -- one product, four spellings of the tier census, two of which printed raw Python
# container repr into a human artifact. MEASURED end to end: (a) gate_report._fmt writes 'T1' on
# every verdict row; (b) format_transcript's header three lines above wrote
# 'tiers executed: 2 of 2  (executed [0, 1]; required [0, 1])' -- list repr, executed before
# required; (c) checkpoint._census_line wrote 'required tiers [0, 1], executed [1]' -- same repr,
# opposite order; (d) exit_contract's PARTIAL_TIER_CENSUS wrote '(required=[0, 1], executed=[1])'
# -- a third form, k=v. A single escalated `pcraft bind` prints all four in one terminal scroll.
# The same file also rendered the same list type two ways: GATE_UNAVAILABLE interpolated
# `skipped` (174 measured characters of quoted repr, on the could-not-run path a plain
# `pip install prompt-craft` user hits first) while GATE_FAIL twenty lines below used ', '.join.
#
# One notation ('T0 T1', matching the verdict rows -- the most-read surface) and one list
# rendering (', '.join, matching GATE_FAIL), at all four sites.
# --------------------------------------------------------------------------------------------

_REPR_FORMS = ("[0, 1]", "[1]", "[0]", "required=", "executed=[")


def _no_container_repr(text: str, where: str) -> None:
    for form in _REPR_FORMS:
        assert form not in text, f"{where} still prints Python container repr ({form!r}): {text!r}"


def test_the_transcript_header_states_the_census_the_way_the_rows_do(sprite_example):
    from pcraft.gate_report import format_transcript
    from pcraft.testing import passing_verifiers

    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion",
    )
    header = next(ln for ln in format_transcript(t).splitlines() if ln.startswith("tiers executed:"))
    assert header.startswith("tiers executed: 2 of 2"), header
    assert "T0 T1" in header, f"the rows say T0/T1 three lines below this one: {header!r}"
    _no_container_repr(header, "the transcript header")


def test_a_complete_census_does_not_reprint_the_count_it_already_stated(sprite_example):
    """'2 of 2' is len() of the two lists that used to be printed beside it. The header states
    what is REQUIRED, and names what is MISSING only when something is."""
    from pcraft.gate_report import format_transcript
    from pcraft.testing import passing_verifiers

    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion",
    )
    header = next(ln for ln in format_transcript(t).splitlines() if ln.startswith("tiers executed:"))
    assert "missing" not in header, f"nothing is missing on a 2-of-2 run: {header!r}"
    assert "executed [" not in header


def test_a_short_census_names_what_is_missing_in_the_same_notation():
    from pcraft.core.gate.harness import GateTranscript, TierCensus
    from pcraft.gate_report import format_transcript

    t = GateTranscript(
        contract_id="char:ashen-reaver",
        overall=Zone.PASS,
        verdicts=[],
        tier_census=TierCensus(required=[0, 1], executed=[1]),
    )
    header = next(ln for ln in format_transcript(t).splitlines() if ln.startswith("tiers executed:"))
    assert "1 of 2" in header
    assert "required T0 T1" in header
    assert "missing T0" in header
    _no_container_repr(header, "the transcript header")


def test_the_checkpoint_census_line_uses_the_same_notation():
    from pcraft.core.gate.checkpoint import build_checkpoint
    from pcraft.core.gate.harness import GateTranscript, TierCensus

    t = GateTranscript(
        contract_id="faction:ashen-pact",
        overall=Zone.PASS,
        verdicts=[],
        tier_census=TierCensus(required=[0, 1], executed=[1]),
    )
    ck = build_checkpoint(t)
    assert "T0 T1" in ck.text and "T1" in ck.text
    _no_container_repr(ck.text, "the checkpoint census line")


def test_the_tier_census_refusal_uses_the_same_notation():
    from pcraft.core.contract.compile_questions import Polarity
    from pcraft.core.contract.schema import Severity
    from pcraft.core.gate.exit_contract import error_from_transcript
    from pcraft.core.gate.harness import AtomVerdict, GateTranscript, TierCensus

    t = GateTranscript(
        contract_id="char:ashen-reaver",
        overall=Zone.PASS,
        verdicts=[
            AtomVerdict(
                atom_id="tabard", polarity=Polarity.affirm, severity=Severity.required,
                score=0.95, zone=Zone.PASS, tier_used=1, tiers_consulted=[1],
                verifier_id="v", reason="score 0.9500 -> PASS",
            )
        ],
        tier_census=TierCensus(required=[0, 1], executed=[1]),
    )
    err = error_from_transcript(t)
    assert err is not None and err.code == "PARTIAL_TIER_CENSUS"
    assert "required T0 T1" in err.message
    assert "missing T0" in err.message
    _no_container_repr(err.message, "PARTIAL_TIER_CENSUS")


def test_the_could_not_run_refusal_joins_its_atom_ids_like_its_sibling(sprite_example):
    """GATE_UNAVAILABLE interpolated a quoted list while GATE_FAIL twenty lines below used
    ', '.join -- the same file, the same data type, two renderings, and the quoted one on the
    path a plain `pip install prompt-craft` user hits first."""
    from pcraft.core.gate.exit_contract import error_from_transcript
    from pcraft.testing import ScriptedVerifier

    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", {1: ScriptedVerifier(lambda _q: None)}, thresholds,
        generator_family="stable-diffusion",
    )
    err = error_from_transcript(t)
    assert err is not None and err.code == "GATE_UNAVAILABLE"
    assert "skipped: tabard, palette" in err.message, err.message
    assert "['" not in err.message, f"quoted list repr in a human message: {err.message!r}"
