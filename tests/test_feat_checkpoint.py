"""F-GATE-FEAT-001 / F-LOOP-FEAT-003 — contrastive human checkpoint.

UNCERTAINTY_GATED_HUMANS is a zone plus this artifact: you probably thought X;
the gate chose Y. GPU-free.
"""

from __future__ import annotations

from pcraft.core.contract.compile_questions import Polarity, compile_questions
from pcraft.core.contract.schema import Severity
from pcraft.core.gate.checkpoint import build_checkpoint
from pcraft.core.gate.harness import AtomVerdict, GateTranscript, TierCensus
from pcraft.core.gate.thresholds import Zone
from pcraft.sample import load_sprite_example, run_mock_loop


def test_uncertain_score_is_contrastive_not_a_zone_name_only():
    _s, resolved, _t, _c = load_sprite_example()
    dag = compile_questions(resolved)
    transcript = GateTranscript(
        contract_id=resolved.id,
        overall=Zone.UNCERTAIN,
        verdicts=[
            AtomVerdict(
                atom_id="face",
                polarity=Polarity.affirm,
                severity=Severity.required,
                score=0.55,
                zone=Zone.UNCERTAIN,
                tier_used=1,
                verifier_id="v",
                reason="near miss",
            )
        ],
        tier_census=TierCensus(required=[0, 1], executed=[0, 1]),
    )
    ck = build_checkpoint(transcript, dag)
    text = ck.text.lower()
    assert "you probably thought" in text
    assert "i chose" in text or "i left" in text
    assert "face" in text
    assert "0.55" in ck.text
    assert ck.lines[0].atom_id == "face"
    assert ck.thought
    assert ck.chose


def test_escalated_loop_carries_the_checkpoint(tmp_path):
    from pcraft.core.loop import orchestrate
    from pcraft.core.loop.orchestrate import LoopConfig
    from pcraft.core.synth.signature import TemplateSynthesizer
    from pcraft.testing import StubGenerator, passing_verifiers

    _s, resolved, thresholds, compiled = load_sprite_example()
    result = orchestrate.run(
        resolved,
        TemplateSynthesizer(compiled),
        StubGenerator(out_dir=tmp_path / "_stub_images"),
        passing_verifiers(scores={"face": 0.55}),
        thresholds,
        config=LoopConfig(thresholds_version=thresholds.version, records_dir=str(tmp_path)),
    )
    assert result.decision == "escalated"
    assert result.checkpoint is not None
    assert "face" in result.checkpoint.text
    assert "you probably thought" in result.checkpoint.text.lower()
    assert result.reason == result.checkpoint.text


def test_bound_run_has_no_checkpoint(tmp_path):
    result = run_mock_loop(records_dir=str(tmp_path))
    assert result.decision == "bound"
    assert result.checkpoint is None


# --------------------------------------------------------------------------- F-2c7b997a
# build_checkpoint derived its entire content from Zone facts and never read tier_census, so an
# escalation whose cause is not a Zone produced an artifact structurally incapable of naming the
# cause -- and that artifact becomes OrchestrationResult.reason, which the CLI prints verbatim.


def _required_pass(atom_id: str) -> AtomVerdict:
    return AtomVerdict(
        atom_id=atom_id,
        polarity=Polarity.affirm,
        severity=Severity.required,
        score=0.95,
        zone=Zone.PASS,
        tier_used=1,
        tiers_consulted=[1],
        verifier_id="v",
        reason="score 0.9500 -> PASS",
    )


def test_the_checkpoint_names_a_short_tier_census():
    """A transcript that rolls up PASS on a 1-of-2 census escalates, and the human artifact used
    to read 'You probably thought nothing needed a human. I escalated (PASS).' with zero lines --
    while error_from_transcript beside it named the census, the required tiers and the executed
    ones."""
    transcript = GateTranscript(
        contract_id="faction:ashen-pact",
        overall=Zone.PASS,
        verdicts=[_required_pass("tabard")],
        tier_census=TierCensus(required=[0, 1], executed=[1]),
    )
    ck = build_checkpoint(transcript)
    text = ck.text.lower()
    assert "1 of 2" in text or "tiers" in text, "the artifact must be able to state a non-Zone cause"
    assert "[0, 1]" in ck.text and "[1]" in ck.text
    assert ck.lines, "a checkpoint with no lines at all is not a checkpoint"
    ck.text.encode("cp437")  # the CLI prints this verbatim on a legacy console


def test_the_checkpoint_does_not_call_a_fully_scored_run_a_missing_score():
    """The reachable door to the same empty artifact: every atom optional, every atom scored,
    every atom passed -- and the text said 'You probably thought a missing score was nothing to
    look at.' That sentence is not merely uninformative, it is false."""
    verdicts = [
        AtomVerdict(
            atom_id="tabard",
            polarity=Polarity.affirm,
            severity=Severity.optional,
            score=0.95,
            zone=Zone.PASS,
            tier_used=1,
            tiers_consulted=[1],
            verifier_id="v",
            reason="score 0.9500 -> PASS",
        )
    ]
    transcript = GateTranscript(
        contract_id="faction:ashen-pact",
        overall=Zone.UNAVAILABLE,
        verdicts=verdicts,
        tier_census=TierCensus(required=[], executed=[]),
    )
    ck = build_checkpoint(transcript)
    assert "missing score" not in ck.text.lower(), "every verifier scored on this run"
    assert "required" in ck.text.lower()
    assert ck.lines, "the artifact has to say something a human can act on"
    ck.text.encode("cp437")


def test_a_normal_uncertain_run_still_reads_the_way_it_did():
    """The common path is not allowed to regress into census prose."""
    _s, resolved, _t, _c = load_sprite_example()
    dag = compile_questions(resolved)
    transcript = GateTranscript(
        contract_id=resolved.id,
        overall=Zone.UNCERTAIN,
        verdicts=[
            AtomVerdict(
                atom_id="tabard",
                polarity=Polarity.affirm,
                severity=Severity.required,
                score=0.55,
                zone=Zone.UNCERTAIN,
                tier_used=1,
                tiers_consulted=[1],
                verifier_id="v",
                reason="near miss",
            )
        ],
        tier_census=TierCensus(required=[0, 1], executed=[0, 1]),
    )
    ck = build_checkpoint(transcript, dag)
    assert "tiers" not in ck.text.lower(), "a complete census must add no line"
    assert len(ck.lines) == 1


# --------------------------------------------------------------------------- F-a6078c7f
# build_checkpoint already had the content as STRUCTURE (one ContrastiveLine per flagged atom)
# and then flattened all of it with ' '.join into ``text`` -- which becomes
# OrchestrationResult.reason, which cli._print_result prints as ``decision: ESCALATED ({reason})``.
# MEASURED: 974 characters, zero newlines, one unbroken parenthesis on the operator's screen,
# while the formatted transcript printed twenty lines below it was fully structured. The human
# decision point was the one artifact that was not.

_ALL_REQUIRED = ("tabard", "sigil", "palette", "skin", "weapon", "face")


def _escalating_run(tmp_path):
    return run_mock_loop(records_dir=str(tmp_path), verifier_scores=dict.fromkeys(_ALL_REQUIRED, 0.05))


def test_the_checkpoint_is_structured_text_not_one_unbroken_line(tmp_path):
    """MEASURED red: len(reason) == 974 and reason.count('\n') == 0."""
    result = _escalating_run(tmp_path)
    text = result.checkpoint.text
    assert result.reason == text, "the CLI prints this verbatim; they must stay the same object"
    assert "\n" in text, "the UNCERTAINTY_GATED_HUMANS artifact shipped as one 974-character line"
    body = text.splitlines()
    assert len(body) == 1 + len(result.checkpoint.lines), (
        "one header line plus one line per flagged atom -- the structure build_checkpoint "
        "already had before it was flattened"
    )


def test_the_summary_is_distinguishable_from_the_detail(tmp_path):
    """The header pair and the per-atom lines used to be joined identically, so nothing
    separated the summary from the detail."""
    result = _escalating_run(tmp_path)
    head, *rows = result.checkpoint.text.splitlines()
    assert head == f"{result.checkpoint.thought} {result.checkpoint.chose}"
    assert rows and all(r.startswith("  - ") for r in rows), (
        "a per-atom line has to be marked as one"
    )


def test_a_claim_that_is_already_a_question_does_not_get_a_full_stop(tmp_path):
    """MEASURED red: 'worn over the torso?.' appeared six times in one run."""
    result = _escalating_run(tmp_path)
    assert "?." not in result.checkpoint.text


def test_the_checkpoint_still_survives_a_legacy_console(tmp_path):
    """F-a6acaab1's guarantee is unchanged by the separator: a newline is ASCII."""
    result = _escalating_run(tmp_path)
    result.checkpoint.text.encode("cp437")
    result.reason.encode("ascii")


# --------------------------------------------------------------------------- F-b1b29cef
# The operator standing at the checkpoint is being asked to accept or repair, and the MARGIN is
# the input to that decision. MEASURED: skin at 0.79 and at 0.41 -- one hundredth from PASS and
# one hundredth from FAIL under vqa 0.80/0.40 -- produced sentences differing only in the number.


def _uncertain_transcript(score: float, *, polarity=Polarity.affirm, band_key="vqa"):
    return GateTranscript(
        contract_id="char:ashen-reaver",
        overall=Zone.UNCERTAIN,
        verdicts=[
            AtomVerdict(
                atom_id="skin",
                polarity=polarity,
                severity=Severity.required,
                score=score,
                zone=Zone.UNCERTAIN,
                tier_used=1,
                tiers_consulted=[1],
                verifier_id="scripted.vqa.v0",
                band_key=band_key,
                reason=f"score {score:.4f} -> UNCERTAIN (band {band_key})",
            )
        ],
        tier_census=TierCensus(required=[0, 1], executed=[0, 1]),
    )


def test_the_checkpoint_prints_the_band_that_graded_the_score():
    _s, _r, table, _c = load_sprite_example()
    ck = build_checkpoint(_uncertain_transcript(0.79), None, table)
    assert "0.79" in ck.text
    assert "0.80" in ck.text and "0.40" in ck.text, (
        "the margin is the input to accept-or-repair; without the band the operator has to open "
        "sprite.calibration.json to learn whether this was nearly a bind or nearly a failure"
    )


def test_a_near_pass_and_a_near_fail_no_longer_read_the_same():
    _s, _r, table, _c = load_sprite_example()
    near_pass = build_checkpoint(_uncertain_transcript(0.79), None, table).text
    near_fail = build_checkpoint(_uncertain_transcript(0.41), None, table).text
    assert near_pass != near_fail
    for text in (near_pass, near_fail):
        assert "0.80" in text and "0.40" in text


def test_a_negate_atoms_band_is_not_printed_backwards():
    """For a must_not probe the band inverts: a HIGH 'is it present?' score is the FAIL. Printing
    'passes at 0.10' for a negate atom would be a confident wrong statement, which is the class
    of defect the band was added to remove."""
    _s, _r, table, _c = load_sprite_example()
    ck = build_checkpoint(
        _uncertain_transcript(0.05, polarity=Polarity.negate, band_key="siglip2"), None, table
    )
    line = ck.text
    assert "0.10" in line and "0.01" in line
    assert "passes at 0.10" not in line, "that is the affirm reading of a negate band"


def test_no_table_renders_exactly_what_it_rendered_before():
    """The argument is optional and additive: a caller without a table is unchanged."""
    _s, _r, _table, _c = load_sprite_example()
    without = build_checkpoint(_uncertain_transcript(0.79))
    assert "0.79" in without.text
    assert "0.80" not in without.text and "0.40" not in without.text
