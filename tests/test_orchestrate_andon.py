from __future__ import annotations

from pcraft.core.contract.compile_questions import Polarity, compile_questions
from pcraft.core.contract.schema import Severity
from pcraft.core.synth.signature import TemplateSynthesizer
from pcraft.sample import run_mock_loop


def test_clean_pass_binds(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    assert res.decision == "bound"
    assert res.record is not None and res.record.decision == "bound"


def test_failed_required_atom_never_binds(tmp_path):
    # the faceless-hero failure: drive the 'face' atom below threshold
    res = run_mock_loop(records_dir=str(tmp_path), verifier_scores={"face": 0.05})
    assert res.decision == "escalated"  # ANDON: a failed required atom blocks bind
    assert any(a.repair for a in res.attempts)  # the repair ladder tried before escalating
    assert res.record.decision == "escalated"


def _require_negations(resolved):
    for mn in resolved.must_not:
        mn.severity = Severity.required


def test_must_not_violation_blocks_bind(tmp_path):
    """ANDON: a violated REQUIRED negation never binds.

    The severity is stated here, not inherited. The example contract's negations are `optional`
    because absence-verification is unmeasured on this stack; this test is about the andon, so it
    sets its own premise rather than borrowing a policy that can change underneath it.
    """
    res = run_mock_loop(
        records_dir=str(tmp_path),
        verifier_scores={"no_human_face": 0.95},
        mutate_contract=_require_negations,
    )
    assert res.decision == "escalated"


def test_an_optional_negation_violation_does_not_block_bind(tmp_path):
    """The other half, and the reason the severity exists.

    Same violated negation, left at the example contract's own `optional`. The check still runs
    and still scores — it simply does not claim the certainty required to block a bind.
    """
    res = run_mock_loop(records_dir=str(tmp_path), verifier_scores={"no_human_face": 0.95})
    assert res.decision == "bound"


def test_contract_is_used_twice(sprite_example):
    """The same atom list synthesizes the prompt AND gates the pixels."""
    _s, resolved, _t, compiled = sprite_example
    synth = TemplateSynthesizer(compiled).synthesize(resolved, "")
    dag = compile_questions(resolved)
    affirm_ids = {q.atom_id for q in dag.questions if q.polarity is Polarity.affirm}
    assert set(synth.atom_coverage) <= affirm_ids
    for atom in resolved.required_atoms():
        assert atom.id in synth.atom_coverage  # consumed by the synthesizer
        assert atom.id in affirm_ids  # consumed by the gate
