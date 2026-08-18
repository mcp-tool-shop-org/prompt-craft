"""F-IMG-FEAT-005 — real DSG. Tier-2 expands the atom, then scores the probes.

GPU-free: fake t2v_metrics. Template QG is the default. Injected QG is read.
A missing entity skips dependents.
"""

from __future__ import annotations

import sys
import types

import pytest

from pcraft.core.contract.compile_questions import Polarity, Question, compile_questions
from pcraft.core.contract.schema import CheckType, Severity
from pcraft.domains.image.verifier.dsg_expand import claim_of, template_expand
from pcraft.domains.image.verifier.dsg_verifier import DSGVerifier, ENTITY_ABSENT
from pcraft.sample import load_sprite_example


def _q(text: str, atom_id: str = "atom") -> Question:
    return Question(
        atom_id=atom_id,
        text=text,
        check_type=CheckType.vqa,
        polarity=Polarity.affirm,
        severity=Severity.required,
    )


def _install_fake_answerer(monkeypatch, scores: dict[str, float] | float):
    fake = types.ModuleType("t2v_metrics")
    seen: list[str] = []

    class _Answerer:
        def __init__(self, model=None):
            self.model = model

        def __call__(self, images, texts):
            text = texts[0]
            seen.append(text)
            if isinstance(scores, dict):
                for needle, value in scores.items():
                    if needle in text:
                        return [[value]]
                return [[0.9]]
            return [[float(scores)]]

    fake.VQAScore = _Answerer
    monkeypatch.setitem(sys.modules, "t2v_metrics", fake)
    return seen


def test_weapon_claim_expands_to_entity_attribute_and_relation():
    q = _q("Does this image show a two-handed battle-axe held in both hands?", "weapon")
    exp = template_expand(q)
    kinds = {p.kind for p in exp.probes}
    assert "claim" in kinds
    assert "entity" in kinds
    assert "attribute" in kinds
    assert "relation" in kinds
    assert any("battle-axe" in p.text and p.kind == "entity" for p in exp.probes)
    assert any("held in both hands" in p.text for p in exp.probes)
    assert any(p.depends_on and p.depends_on.endswith(":entity") for p in exp.probes)


def test_face_with_tusks_is_an_attribute_not_a_second_entity():
    q = _q("Does this image show a visible orcish face with tusks?", "face")
    exp = template_expand(q)
    assert any("tusks" in p.text and p.kind == "attribute" for p in exp.probes)
    assert any(p.kind == "entity" and "face" in p.text for p in exp.probes)


def test_claim_of_strips_the_vqa_wrapper():
    assert claim_of(_q("Does this image show a crimson tabard?")) == "a crimson tabard"


def test_shipped_vqa_atoms_all_expand_past_the_root():
    _s, resolved, _t, _c = load_sprite_example()
    dag = compile_questions(resolved)
    vqa = [q for q in dag.questions if q.check_type is CheckType.vqa]
    assert vqa
    for q in vqa:
        exp = template_expand(q)
        assert len(exp.probes) >= 2, q.text


def test_score_is_the_mean_of_the_probes_that_ran(monkeypatch):
    _install_fake_answerer(monkeypatch, 0.80)
    v = DSGVerifier()
    score = v.score("x.png", _q("Does this image show a crimson tabard?", "tabard"))
    assert score == pytest.approx(0.80)
    assert v.last_expansion is not None
    assert v.last_expansion.source == "template.dsg.v1"
    assert len(v.last_expansion.probes) >= 2


def test_a_missing_entity_skips_dependents(monkeypatch):
    _install_fake_answerer(monkeypatch, {"tabard": 0.10, "crimson": 0.99})
    v = DSGVerifier()
    score = v.score("x.png", _q("Does this image show a crimson tabard?", "tabard"))
    assert score is not None
    assert score < ENTITY_ABSENT
    skipped = [pid for pid, s in (v.last_expansion.scores or {}).items() if s is None]
    assert any(pid.endswith(":attr:0") for pid in skipped)


def test_injected_qg_is_what_the_answerer_sees(monkeypatch):
    from pcraft.domains.image.verifier.dsg_expand import SubProbe

    seen = _install_fake_answerer(monkeypatch, 0.7)

    def qg(question: Question) -> list[SubProbe]:
        return [
            SubProbe(id="only", text="Does this image show the injected probe?", kind="entity"),
        ]

    v = DSGVerifier(qg_model="test-qg", qg=qg)
    v.score("x.png", _q("Does this image show a crimson tabard?"))
    assert seen == ["Does this image show the injected probe?"]
    assert v.last_expansion is not None
    assert v.last_expansion.source == "qg:test-qg"


def test_qg_model_label_is_on_the_expansion():
    v = DSGVerifier()
    assert v.qg_model == "template.dsg.v1"
    exp = v.expand(_q("Does this image show a tabard?"))
    assert exp.source == "template.dsg.v1"
