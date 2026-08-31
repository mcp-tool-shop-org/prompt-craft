from __future__ import annotations

import math

from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.contract.schema import Severity
from pcraft.core.gate import harness
from pcraft.core.gate.thresholds import Zone
from pcraft.testing import ScriptedVerifier, passing_verifiers


def test_parent_fail_forces_child_na(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier({"tabard": 0.05})  # tabard fails; sigil depends_on tabard
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["tabard"].zone is Zone.FAIL
    assert verdicts["sigil"].zone is Zone.NA  # not evaluated; not a false confirmation
    assert t.overall is Zone.FAIL


def test_all_pass_rolls_up_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    # Both required tiers registered: a lone Tier-1 verifier no longer covers Tier-0 atoms
    # (a missing wanted tier is SKIPPED, not fallen forward), so a PASS assertion has to
    # actually run the gate it claims passed.
    t = harness.evaluate(dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.PASS
    assert t.tier_census.n == t.tier_census.m


def test_skipped_required_atom_is_uncertain_not_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)

    def scorer(q):
        if q.atom_id == "face":
            return None  # verifier cannot answer -> SKIPPED
        return 0.02 if q.polarity.value == "negate" else 0.95

    v = ScriptedVerifier(scorer)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["face"].zone is Zone.SKIPPED
    assert t.overall is Zone.UNCERTAIN  # an unconfirmed required atom never silently passes


def test_must_not_violation_fails(sprite_example):
    """A violated REQUIRED negation rolls the whole transcript to FAIL.

    The severity is set here rather than inherited from the example contract, whose negations are
    `optional` because absence-verification is unmeasured on this stack. This test is about the
    mechanism, so it states its own premise instead of borrowing a policy that can change.
    """
    _s, resolved, thresholds, _c = sprite_example
    for mn in resolved.must_not:
        mn.severity = Severity.required
    dag = compile_questions(resolved)
    # the forbidden 'human face' IS present -> high score on a negate probe -> FAIL
    v = ScriptedVerifier({"no_human_face": 0.95})
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    verdicts = {x.atom_id: x for x in t.verdicts}
    assert verdicts["no_human_face"].zone is Zone.FAIL
    assert t.overall is Zone.FAIL


# --------------------------------------------------------------------------- F-GATE-FEAT-003 wrap verifier.score(); reject NaN / out of range
# NaN used to compare False against both bands and fall through to UNCERTAIN.
# 1.5 used to clear the high band and become a false PASS.


def test_nan_score_is_skipped_not_uncertain(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: math.nan)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    scored = [x for x in t.verdicts if x.score is not None]
    assert scored == []
    # A SKIPPED parent still forces children to NA; none of them is a zoned score.
    assert all(x.zone in (Zone.SKIPPED, Zone.NA) for x in t.verdicts)
    assert t.overall is Zone.UNAVAILABLE
    assert any("rejected" in x.reason and "[0, 1]" in x.reason for x in t.verdicts)


def test_out_of_range_score_is_skipped_not_a_false_pass(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: 1.5)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is not Zone.PASS
    assert all(x.score is None for x in t.verdicts)
    assert any("1.5" in x.reason for x in t.verdicts)


def test_negative_score_is_skipped_not_a_false_fail(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: -0.1)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert all(x.zone is not Zone.FAIL for x in t.verdicts)


def test_infinite_score_is_skipped(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: math.inf)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert all(x.score is None for x in t.verdicts)


def test_score_exception_is_skipped_not_a_crash(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)

    def boom(_q):
        raise RuntimeError("instrument exploded")

    v = ScriptedVerifier(boom)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.UNAVAILABLE
    assert any("RuntimeError" in x.reason for x in t.verdicts)


def test_evaluate_stamps_the_thresholds_version(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion")
    assert t.thresholds_version == thresholds.version == "sprite.cal.v1"


# --------------------------------------------------------------------------- F-00cfd3f8
# The band is chosen by the INSTRUMENT that produced the number, not by the atom's declared
# check_type, whenever the two name different band families. The shipped bands are almost an
# order of magnitude apart (siglip2 high=0.10 vs palette high=0.85), so grading one
# instrument's confident answer on another's scale is a WRONG verdict, not an unconfirmed one.


def _verdict(transcript, atom_id):
    return {v.atom_id: v for v in transcript.verdicts}[atom_id]


def test_a_delegated_screen_score_is_zoned_on_the_screen_band(sprite_example):
    """The Tier-0 router hands a ``palette`` atom whose enum carries no hex colours to SigLIP2 and
    reports ``siglip2.screen.v1`` as the instrument. The score comes back on the SigLIP2 scale and
    used to be graded against the palette band: 0.30 is a strong SigLIP2 match (high 0.10) and a
    confident palette FAIL (low 0.50). Same number, opposite answers."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    screen = ScriptedVerifier(
        {"palette": 0.30}, family="siglip2", tier=0, verifier_id="siglip2.screen.v1"
    )
    t = harness.evaluate(dag, "x.png", {0: screen}, thresholds, generator_family="stable-diffusion")
    v = _verdict(t, "palette")
    assert v.verifier_id == "siglip2.screen.v1"
    assert v.band_key == "siglip2", "the band must follow the instrument that produced the number"
    assert v.zone is Zone.PASS, "0.30 is a FAIL only on someone else's calibration"


def test_a_palette_score_still_uses_the_palette_band(sprite_example):
    """The other direction: when the histogram really did measure it, nothing moves."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    hist = ScriptedVerifier(
        {"palette": 0.30}, family="palette-hist", tier=0, verifier_id="palette.hist.v1"
    )
    t = harness.evaluate(dag, "x.png", {0: hist}, thresholds, generator_family="stable-diffusion")
    v = _verdict(t, "palette")
    assert v.band_key == "palette"
    assert v.zone is Zone.FAIL  # 0.30 <= palette low 0.50


def test_an_instrument_that_names_no_band_keeps_the_check_type_band(sprite_example):
    """``scripted.siglip2.v0`` leads with ``scripted``, which is not a band in the table, so the
    atom's declared check_type stays the answer. The rule may only ever redirect to a band the
    table actually declares -- inventing one out of an arbitrary verifier_id would be a second
    silent re-scale, wearing the first one's fix as a disguise."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion")
    v = _verdict(t, "palette")
    assert v.verifier_id == "scripted.siglip2.v0"
    assert v.band_key == "palette"
    assert v.zone is Zone.PASS


# --------------------------------------------------------------------------- F-b1b29cef
# Every score the operator reads was printed in one column whose meaning changes per row, and the
# number that would make it readable -- the band that graded it -- was never printed anywhere.
# The shipped sprite table is palette 0.85/0.50, vqa 0.80/0.40, siglip2 0.10/0.01: three scales,
# the outermost pair fifty times apart, all rendered as bare floats in the same column. MEASURED,
# real ``pcraft gate``: ``[FAIL] palette 0.333`` above ``[PASS] no_rival_colours 0.005``. Ten
# times smaller and it passes; the only disambiguator on the line was the band's NAME, which
# F-00cfd3f8 added for attribution, not for calibration. ``reason`` is where the band name already
# is, so it is where the numbers go -- which puts them on every renderer that prints a verdict
# line without any renderer having to be taught about the table.


def test_a_verdict_reason_names_the_numbers_its_band_graded_by(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", passing_verifiers(scores={"palette": 0.333}), thresholds,
        generator_family="stable-diffusion",
    )
    palette = {v.atom_id: v for v in t.verdicts}["palette"]
    assert palette.zone is Zone.FAIL
    assert "band palette" in palette.reason, "the attribution F-00cfd3f8 added is not removed"
    assert "0.85" in palette.reason and "0.50" in palette.reason, (
        "a bare 0.333 in a shared column cannot be read without the band it was graded against"
    )


def test_two_atoms_on_different_scales_are_now_distinguishable(sprite_example):
    """The measured pair: a 0.050 FAIL sitting eight lines above a 0.005 PASS."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", passing_verifiers(scores={"tabard": 0.05}), thresholds,
        generator_family="stable-diffusion",
    )
    by_id = {v.atom_id: v for v in t.verdicts}
    assert by_id["tabard"].zone is Zone.FAIL and by_id["no_rival_colours"].zone is Zone.PASS
    assert "0.80" in by_id["tabard"].reason and "0.40" in by_id["tabard"].reason
    assert "0.10" in by_id["no_rival_colours"].reason


def test_a_negate_atoms_band_is_not_reported_with_the_affirm_reading(sprite_example):
    """For a must_not probe the band inverts: a HIGH 'is it present?' score is the FAIL. Printing
    the affirm reading on a negate row would be a confident wrong statement about calibration."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", passing_verifiers(), thresholds, generator_family="stable-diffusion",
    )
    negate = {v.atom_id: v for v in t.verdicts}["no_rival_colours"]
    assert "PASS >=" not in negate.reason, "0.10 is where a must_not probe FAILS, not passes"
    assert "FAIL >=0.10" in negate.reason and "PASS <=0.01" in negate.reason


def test_an_atom_that_never_scored_states_no_band(sprite_example):
    """band_key is empty when nothing scored; inventing a band there would be the same silent
    re-scale F-00cfd3f8 removed, wearing its fix as a disguise."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    v = ScriptedVerifier(lambda _q: None)
    t = harness.evaluate(dag, "x.png", {v.tier: v}, thresholds, generator_family="stable-diffusion")
    for verdict in t.verdicts:
        assert verdict.score is None
        assert "PASS >=" not in verdict.reason and "PASS <=" not in verdict.reason


# --------------------------------------------------------------------------- coordinator addition
# (completing image-domain's landed half.) Tier0Router.score_detail() (a per-colour hit breakdown)
# and DSGVerifier.localization_detail() produce facts that had no route to a reader: AtomVerdict is
# extra="forbid" and evaluate() composes ``reason`` itself, so a verifier's channel to the
# transcript was one float wide. The seam is duck-typed on purpose -- the implementations live in
# another package, and the doubles below are what pin the contract from this side.


class _DetailedVerifier:
    """A Tier-0 verifier that also explains itself, the way Tier0Router now does."""

    family = "siglip2"
    tier = 0
    verifier_id = "palette.hist.v1"
    version = "v1"

    def __init__(self, score_value=0.333, detail="missing colour bone-white"):
        self._score = score_value
        self._detail = detail
        self.detail_calls = 0

    def score(self, image_path, question):
        return self._score

    def score_detail(self, image_path, question):
        self.detail_calls += 1
        return self._detail


def _evaluate_with(verifier, resolved, thresholds):
    dag = compile_questions(resolved)
    return harness.evaluate(
        dag, "x.png", {verifier.tier: verifier}, thresholds, generator_family="stable-diffusion"
    )


def test_a_verifier_that_can_explain_itself_reaches_the_transcript(sprite_example):
    _s, resolved, thresholds, _c = sprite_example
    v = _DetailedVerifier()
    t = _evaluate_with(v, resolved, thresholds)
    palette = {x.atom_id: x for x in t.verdicts}["palette"]
    assert palette.zone is Zone.FAIL
    assert palette.detail == "missing colour bone-white"
    assert v.detail_calls, "the seam has to actually ask"


def test_the_rendered_verdict_line_names_what_the_instrument_saw(sprite_example):
    from pcraft.gate_report import format_transcript

    _s, resolved, thresholds, _c = sprite_example
    t = _evaluate_with(_DetailedVerifier(), resolved, thresholds)
    assert "missing colour bone-white" in format_transcript(t)


def test_a_verifier_with_no_detail_renders_exactly_what_it_did_before(sprite_example):
    """Absent field == old shape, on the model and on the rendered line. A verifier that
    publishes neither method is the normal case, not an error.

    ⚑ REWRITTEN IN PLACE (F-00cc16d9). This asserted ``row.endswith(v.reason)`` -- i.e. it
    pinned the reason ONTO the verdict row, which is what made the plainest possible row 121
    characters and put every row over both standard terminal widths. The reason (and the
    ``detail`` beside it) now hang on their own labelled continuation lines under the atom, so
    the property this test is really about -- an absent detail adds NOTHING -- is asserted as
    the absence of a ``saw:`` line rather than as the row's last characters.
    """
    from pcraft.gate_report import format_transcript

    _s, resolved, thresholds, _c = sprite_example
    plain = ScriptedVerifier(
        {"palette": 0.333}, family="siglip2", tier=0, verifier_id="palette.hist.v1"
    )
    assert not hasattr(plain, "score_detail") and not hasattr(plain, "localization_detail")
    t = _evaluate_with(plain, resolved, thresholds)
    assert all(v.detail is None for v in t.verdicts)

    rendered = format_transcript(t)
    assert "saw:" not in rendered, "an absent detail appends nothing at all"
    for v in t.verdicts:
        row = next(line for line in rendered.splitlines() if f" {v.atom_id:18} " in line)
        assert row.rstrip().endswith(f"{v.polarity.value}/{v.severity.value}"), (
            "the row ends at its last fixed column; everything secondary hangs below it"
        )


def test_a_detail_method_that_raises_cannot_change_a_verdict(sprite_example):
    """Commentary on a score that already exists must never turn a scored atom into a SKIPPED one
    -- the same discipline _safe_score applies to scoring itself."""
    _s, resolved, thresholds, _c = sprite_example

    class _Exploding(_DetailedVerifier):
        def score_detail(self, image_path, question):
            raise RuntimeError("the breakdown blew up")

    t = _evaluate_with(_Exploding(), resolved, thresholds)
    palette = {x.atom_id: x for x in t.verdicts}["palette"]
    assert palette.zone is Zone.FAIL, "the score stands"
    assert palette.score == 0.333
    assert palette.detail is None


def test_a_detail_method_that_takes_no_arguments_is_still_asked(sprite_example):
    """The implementations live in another package; one wrong guess about the signature would
    silently drop the field rather than fail loudly, so both plausible shapes are accepted."""
    _s, resolved, thresholds, _c = sprite_example

    class _NoArgs(_DetailedVerifier):
        def score_detail(self):
            return "hit 2 of 3 declared colours"

    t = _evaluate_with(_NoArgs(), resolved, thresholds)
    assert {x.atom_id: x for x in t.verdicts}["palette"].detail == "hit 2 of 3 declared colours"


def test_a_mapping_detail_is_rendered_rather_than_stored_raw(sprite_example):
    """The field is a string because it exists to be read on a verdict line."""
    _s, resolved, thresholds, _c = sprite_example

    class _Mapping(_DetailedVerifier):
        def score_detail(self, image_path, question):
            return {"ash-grey": "hit", "bone-white": "missing"}

    detail = {x.atom_id: x for x in _evaluate_with(_Mapping(), resolved, thresholds).verdicts}[
        "palette"
    ].detail
    assert isinstance(detail, str)
    assert "bone-white=missing" in detail and "ash-grey=hit" in detail


def test_the_localization_detail_name_is_accepted_too(sprite_example):
    """DSGVerifier publishes localization_detail, not score_detail."""
    _s, resolved, thresholds, _c = sprite_example

    class _Localizer(_DetailedVerifier):
        score_detail = None  # not callable -> skipped, the next name is tried

        def localization_detail(self, image_path, question):
            return "looked at the torso region"

    t = _evaluate_with(_Localizer(), resolved, thresholds)
    assert {x.atom_id: x for x in t.verdicts}["palette"].detail == "looked at the torso region"
