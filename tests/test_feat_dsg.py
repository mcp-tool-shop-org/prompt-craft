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
from pcraft.domains.image.verifier.dsg_verifier import ENTITY_ABSENT, DSGVerifier
from pcraft.errors import PromptCraftError
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


# ============= F-f5cc9257 (family-of-call-sites: the image domain's own DAG walker got no guard)
# core/contract/compile_questions.py::QuestionDAG.topological carries a 'visiting' set and raises
# CONTRACT_CYCLIC_DEPENDS_ON, and harness.evaluate goes further, explicitly catching (ValueError,
# RecursionError) around it (harness.py:163) because the repo already decided a cycle must be a named
# code and never a bare exception. DSGExpansion.topological is the identical recursive visit pattern
# with no 'visiting' set and no depth bound: it adds to 'done' only AFTER the recursive call, so a
# two-probe cycle recurses forever.
#
# MEASURED before the fix: probes p1.depends_on='p2' and p2.depends_on='p1' made
# DSGExpansion.topological raise a raw RecursionError ('maximum recursion depth exceeded') -- a
# RuntimeError, not a PromptCraftError -- while the sibling QuestionDAG.topological on the same shape
# raised PromptCraftError code=CONTRACT_CYCLIC_DEPENDS_ON. Driven through DSGVerifier.score it was
# then swallowed by harness._safe_score's 'except Exception' into a SKIPPED verdict reading
# 'dsg.localizer.v1 raised RecursionError: maximum recursion depth exceeded', so a malformed
# expansion presented as an UNAVAILABLE INSTRUMENT rather than as a malformed expansion.
#
# Reachability, stated honestly: the shipped template_expand never emits a cycle (it always emits the
# entity probe every attribute/relation depends on), so this is reachable only through the injected
# 'qg' slot -- but that slot is a documented, advertised extension point, and an injected QG is
# exactly the caller whose edges nothing validates. Duplicate probe ids are the second half:
# MEASURED, an expansion with two probes sharing id 'p1' constructed fine and topological() returned
# 1 probe for 2 in -- the same silent dedup that ResolvedContract refuses at construction time.


def _cyclic_probes():
    from pcraft.domains.image.verifier.dsg_expand import SubProbe

    return [
        SubProbe(id="p1", text="Does this image show a?", kind="entity", depends_on="p2"),
        SubProbe(id="p2", text="Does this image show b?", kind="entity", depends_on="p1"),
    ]


def test_a_cyclic_expansion_is_refused_by_name_not_by_recursion_error():
    from pcraft.domains.image.verifier.dsg_expand import DSGExpansion

    exp = DSGExpansion(atom_id="a", source="qg:test-qg", probes=_cyclic_probes())
    with pytest.raises(PromptCraftError) as exc:
        exp.topological()
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"
    assert "p1" in exc.value.message and "p2" in exc.value.message


def test_the_dsg_walker_refuses_the_same_shape_its_sibling_refuses():
    """The whole point of the family-of-call-sites finding: two walkers, one law. The sibling in
    core/contract already raises this code on this shape."""
    from pcraft.core.contract.compile_questions import Polarity, Question, QuestionDAG
    from pcraft.core.contract.schema import CheckType, Severity
    from pcraft.domains.image.verifier.dsg_expand import DSGExpansion

    def _atom(atom_id: str, parent: str) -> Question:
        return Question(
            atom_id=atom_id,
            text="Does this image show a thing?",
            check_type=CheckType.vqa,
            polarity=Polarity.affirm,
            severity=Severity.required,
            depends_on=parent,
        )

    sibling = QuestionDAG(contract_id="c", questions=[_atom("p1", "p2"), _atom("p2", "p1")])
    with pytest.raises(Exception) as sibling_exc:
        sibling.topological()
    mine = DSGExpansion(atom_id="a", source="qg:test-qg", probes=_cyclic_probes())
    with pytest.raises(PromptCraftError) as my_exc:
        mine.topological()
    assert getattr(sibling_exc.value, "code", None) == my_exc.value.code


def test_a_self_dependent_probe_is_a_cycle_too():
    from pcraft.domains.image.verifier.dsg_expand import DSGExpansion, SubProbe

    exp = DSGExpansion(
        atom_id="a",
        source="qg:test-qg",
        probes=[SubProbe(id="p1", text="Does this image show a?", kind="entity", depends_on="p1")],
    )
    with pytest.raises(PromptCraftError) as exc:
        exp.topological()
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"


def test_an_injected_cyclic_qg_is_refused_rather_than_read_as_an_unavailable_instrument(monkeypatch):
    """score() called expansion.topological() unguarded, in contrast to _ask() directly above it
    which classifies everything the answerer can throw. The RecursionError escaped unclassified and
    harness._safe_score turned it into 'dsg.localizer.v1 raised RecursionError' -- a SKIPPED verdict
    blaming the instrument for the caller's malformed expansion."""
    _install_fake_answerer(monkeypatch, 0.9)
    v = DSGVerifier(qg_model="test-qg", qg=lambda question: _cyclic_probes())
    with pytest.raises(PromptCraftError) as exc:
        v.score("x.png", _q("Does this image show a crimson tabard?"))
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"


def test_duplicate_probe_ids_are_refused_at_construction_not_silently_deduped():
    """MEASURED: two probes sharing id 'p1' constructed fine and topological() returned 1 for 2 in --
    a probe simply disappeared from the order. ResolvedContract refuses the same shape at
    construction time (CONTRACT_DUPLICATE_ATOM_ID) precisely so a walker's dedup is never the
    enforcement mechanism."""
    from pcraft.domains.image.verifier.dsg_expand import DSGExpansion, SubProbe

    with pytest.raises(PromptCraftError) as exc:
        DSGExpansion(
            atom_id="a",
            source="qg:test-qg",
            probes=[
                SubProbe(id="p1", text="Does this image show a?", kind="entity"),
                SubProbe(id="p1", text="Does this image show b?", kind="entity"),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_PROBE_ID"
    assert "p1" in exc.value.message


def test_an_injected_qg_with_duplicate_ids_is_refused_by_name(monkeypatch):
    from pcraft.domains.image.verifier.dsg_expand import SubProbe

    _install_fake_answerer(monkeypatch, 0.9)

    def qg(question):
        return [
            SubProbe(id="dup", text="Does this image show a?", kind="entity"),
            SubProbe(id="dup", text="Does this image show b?", kind="entity"),
        ]

    v = DSGVerifier(qg_model="test-qg", qg=qg)
    with pytest.raises(PromptCraftError) as exc:
        v.score("x.png", _q("Does this image show a crimson tabard?"))
    assert exc.value.code == "CONTRACT_DUPLICATE_PROBE_ID"


def test_the_template_expander_still_produces_a_parent_first_order(monkeypatch):
    """The guards must not break the shipped decomposer, which is the pinned default QG."""
    _install_fake_answerer(monkeypatch, 0.9)
    exp = template_expand(_q("Does this image show a two-handed battle-axe held in both hands?"))
    order = exp.topological()
    assert len(order) == len(exp.probes)
    seen: set[str] = set()
    for probe in order:
        if probe.depends_on:
            assert probe.depends_on in seen, "a child was ordered before its parent"
        seen.add(probe.id)


def test_shipped_expansions_all_survive_the_new_guards():
    """Every vqa atom in the shipped contract still expands and still orders."""
    _s, resolved, _t, _c = load_sprite_example()
    dag = compile_questions(resolved)
    vqa = [q for q in dag.questions if q.check_type is CheckType.vqa]
    assert vqa
    for q in vqa:
        exp = template_expand(q)
        assert len(exp.topological()) == len(exp.probes)
