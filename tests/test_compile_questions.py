from __future__ import annotations

import pytest

from pcraft.core.contract.compile_questions import (
    Polarity,
    Question,
    QuestionDAG,
    compile_questions,
)
from pcraft.core.contract.schema import (
    Atom,
    CheckType,
    MustNot,
    ResolvedContract,
    Severity,
    Spatial,
    SpatialKind,
)
from pcraft.errors import PromptCraftError


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


def _cyclic_dag() -> QuestionDAG:
    """A 2-cycle built straight from Questions.

    [!] CORRECTED IN PLACE (F-2b317b56). This test used to build a ResolvedContract and
    compile it. A cycle is now refused at ResolvedContract CONSTRUCTION, which is the point
    of that fix -- so the fixture would have raised before it ever reached the walk it exists
    to exercise. Building the DAG directly is also the honest shape for what this arm now is:
    defence in depth for a QuestionDAG assembled with no ResolvedContract behind it, which is
    exactly how the harness tests build theirs.
    """
    return QuestionDAG(
        contract_id="c",
        questions=[
            Question(
                atom_id="a", text="an a?", check_type=CheckType.vqa,
                polarity=Polarity.affirm, severity=Severity.required, depends_on="b",
            ),
            Question(
                atom_id="b", text="a b?", check_type=CheckType.vqa,
                polarity=Polarity.affirm, severity=Severity.required, depends_on="a",
            ),
        ],
    )


def test_cycle_raises():
    """[!] CORRECTED IN PLACE. This asserted `pytest.raises(ValueError)`. A bare ValueError is
    not a refusal this system can classify: the CLI backstop reports it as RUNTIME_UNEXPECTED
    (exit 2, "prompt-craft crashed") when the truth is a malformed contract (exit 1, "fix your
    input"). Gates raise named codes, never bare errors."""
    with pytest.raises(PromptCraftError) as exc:
        _cyclic_dag().topological()
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"
    assert exc.value.exit_code == 1


def test_a_cyclic_resolved_contract_never_gets_as_far_as_the_walk():
    """The real door for this defect. `pcraft validate` compiles the DAG but never walks it,
    so before the load-time refusal a cycle passed validate with "ok" and exit 0, and only
    died later in bind/gate."""
    with pytest.raises(PromptCraftError) as exc:
        ResolvedContract(
            id="c", level="character", lineage=["c"], identity_refs=[], must_not=[],
            must_have=[
                Atom(id="a", claim="a", check_type=CheckType.vqa, depends_on="b"),
                Atom(id="b", claim="b", check_type=CheckType.vqa, depends_on="a"),
            ],
        )
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"
