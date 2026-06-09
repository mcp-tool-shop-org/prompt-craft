from __future__ import annotations

import pytest

from pcraft.core.contract.compile_questions import Polarity, compile_questions
from pcraft.core.contract.schema import Atom, CheckType, ResolvedContract, Severity


def test_atoms_and_must_not_become_questions(sprite_example):
    _s, resolved, _t, _c = sprite_example
    dag = compile_questions(resolved)
    affirm = [q for q in dag.questions if q.polarity is Polarity.affirm]
    negate = [q for q in dag.questions if q.polarity is Polarity.negate]
    assert len(affirm) == len(resolved.must_have)
    assert len(negate) == len(resolved.must_not)
    # every must_not probe is treated as blocking-required
    assert all(q.severity is Severity.required for q in negate)


def test_depends_on_edge_preserved(sprite_example):
    _s, resolved, _t, _c = sprite_example
    dag = compile_questions(resolved)
    sigil = dag.by_id("sigil")
    assert sigil.depends_on == "tabard"


def test_topological_orders_parents_first(sprite_example):
    _s, resolved, _t, _c = sprite_example
    dag = compile_questions(resolved)
    order = [q.atom_id for q in dag.topological()]
    assert order.index("tabard") < order.index("sigil")


def test_cycle_raises():
    resolved = ResolvedContract(
        id="c", level="character", lineage=["c"], identity_refs=[], must_not=[],
        must_have=[
            Atom(id="a", claim="a", check_type=CheckType.vqa, depends_on="b"),
            Atom(id="b", claim="b", check_type=CheckType.vqa, depends_on="a"),
        ],
    )
    dag = compile_questions(resolved)
    with pytest.raises(ValueError):
        dag.topological()
