from __future__ import annotations

from pcraft.core.contract.compile_questions import Polarity, compile_questions
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


def test_must_not_violation_blocks_bind(tmp_path):
    # the forbidden human face IS present -> must_not violated -> never binds
    res = run_mock_loop(records_dir=str(tmp_path), verifier_scores={"no_human_face": 0.95})
    assert res.decision == "escalated"


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
