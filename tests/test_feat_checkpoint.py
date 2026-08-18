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
