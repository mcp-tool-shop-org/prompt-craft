from __future__ import annotations

import pytest

from pcraft.core.contract.compile_questions import Polarity, compile_questions
from pcraft.core.contract.schema import (
    Atom,
    CheckType,
    MustNot,
    ResolvedContract,
    Spatial,
    SpatialKind,
)


def test_atoms_and_must_not_become_questions(sprite_example):
    _s, resolved, _t, _c = sprite_example
    dag = compile_questions(resolved)
    affirm = [q for q in dag.questions if q.polarity is Polarity.affirm]
    negate = [q for q in dag.questions if q.polarity is Polarity.negate]
    assert len(affirm) == len(resolved.must_have)
    assert len(negate) == len(resolved.must_not)
    # ⚑ CORRECTED IN PLACE. This asserted `all(q.severity is Severity.required for q in negate)`
    # under the comment "every must_not probe is treated as blocking-required". That was a claim
    # about the SYSTEM which only held because `MustNot` had no severity field. A negation now
    # carries the blocking power its evidence supports, so what compilation must preserve is the
    # contract's own severity — not a constant.
    assert [q.severity for q in negate] == [mn.severity for mn in resolved.must_not]


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


def test_must_not_spatial_reaches_the_question():
    resolved = ResolvedContract(
        id="c",
        level="character",
        lineage=["c"],
        identity_refs=[],
        must_have=[],
        must_not=[
            MustNot(
                id="no_shield",
                claim="a shield",
                spatial=Spatial(kind=SpatialKind.region, ref="torso"),
            )
        ],
    )
    dag = compile_questions(resolved)
    q = dag.by_id("no_shield")
    assert q is not None
    assert q.spatial is not None
    assert q.spatial.ref == "torso"
    assert q.polarity is Polarity.negate


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
