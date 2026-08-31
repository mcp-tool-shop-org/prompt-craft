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
