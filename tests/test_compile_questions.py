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


# ---------------------------------------------------------------------------
# F-65297c98 -- both producers of CONTRACT_CYCLIC_DEPENDS_ON must name the PATH
#
# Same code, same conceptual defect, two different amounts of information. The
# construction-time arm (schema._reject_cyclic_depends_on -- the real author-facing door)
# says "has a depends_on cycle: tabard -> sigil -> tabard". This arm said "at atom
# 'tabard'": the one node where the DFS revisit landed, with no way to see what it loops
# through. test_cycle_raises only asserted .code and .exit_code, so the gap was unpinned.
# ---------------------------------------------------------------------------


def _self_edge_dag() -> QuestionDAG:
    """The degenerate cycle: one question that depends_on itself."""
    return QuestionDAG(
        contract_id="c",
        questions=[
            Question(
                atom_id="a", text="an a?", check_type=CheckType.vqa,
                polarity=Polarity.affirm, severity=Severity.required, depends_on="a",
            )
        ],
    )


def test_the_dag_cycle_refusal_names_the_path_not_just_the_landing_atom():
    with pytest.raises(PromptCraftError) as exc:
        _cyclic_dag().topological()
    assert "a -> b -> a" in exc.value.message


def test_a_self_edge_in_the_dag_prints_as_a_path_too():
    with pytest.raises(PromptCraftError) as exc:
        _self_edge_dag().topological()
    assert "a -> a" in exc.value.message


def test_both_producers_of_the_cycle_code_report_the_same_path():
    """The finding's actual ask, stated as a comparison rather than as a string literal:
    the same 2-cycle, entered through each of the two doors, must yield the same path.
    Message wording is not the covered surface -- the code is -- so this pins the SHAPE
    the two refusals share, which is what a reader compares when either one fires."""
    with pytest.raises(PromptCraftError) as dag_exc:
        _cyclic_dag().topological()
    with pytest.raises(PromptCraftError) as contract_exc:
        ResolvedContract(
            id="c", level="character", lineage=["c"], identity_refs=[], must_not=[],
            must_have=[
                Atom(id="a", claim="a", check_type=CheckType.vqa, depends_on="b"),
                Atom(id="b", claim="b", check_type=CheckType.vqa, depends_on="a"),
            ],
        )
    assert dag_exc.value.code == contract_exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"
    marker = "has a depends_on cycle: "
    assert dag_exc.value.message.split(marker)[-1] == contract_exc.value.message.split(marker)[-1]


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


# ---------------------------------------------------------------------------
# F-2c77d698 -- the compiled Question must CARRY the atom's spatial declaration
#
# The coordinated half of image-domain's region-localized verification: a verifier that
# scores a named region needs the region to survive compilation, and a verifier that has
# none must see the field absent rather than defaulted.
#
# MEASURED at 5c62d9a, before any edit in this wave: compile_questions already passes
# `spatial=atom.spatial` on the affirm arm and `spatial=mn.spatial` on the negate arm, so
# the pass-through EXISTS -- but only the negate arm was pinned
# (test_must_not_spatial_reaches_the_question above). The must_have arm, the absent case,
# and the pose kind were unpinned, which is what makes a downstream domain's dependency on
# this field a hope rather than a contract. These tests are the pin, not a fix.
# ---------------------------------------------------------------------------


def _one_atom_contract(atom: Atom) -> ResolvedContract:
    return ResolvedContract(
        id="c", level="character", lineage=["c"], identity_refs=[], must_have=[atom], must_not=[]
    )


def test_a_region_atom_compiles_to_a_question_carrying_its_region():
    resolved = _one_atom_contract(
        Atom(
            id="face",
            claim="a visible orcish face",
            check_type=CheckType.vqa,
            spatial=Spatial(kind=SpatialKind.region, ref="head"),
        )
    )
    q = compile_questions(resolved).by_id("face")
    assert q.polarity is Polarity.affirm
    assert q.spatial is not None
    assert q.spatial.kind is SpatialKind.region
    assert q.spatial.ref == "head"


def test_a_pose_atom_keeps_its_kind_through_compilation():
    """`pose` and `region` mean different things to a verifier -- a pose ref is a ControlNet
    image that locks geometry, not an image region to score. The kind may not be flattened."""
    resolved = _one_atom_contract(
        Atom(
            id="weapon",
            claim="a two-handed battle-axe",
            check_type=CheckType.vqa,
            spatial=Spatial(kind=SpatialKind.pose, ref="poses/two-hand-weapon.openpose.png"),
        )
    )
    q = compile_questions(resolved).by_id("weapon")
    assert q.spatial.kind is SpatialKind.pose
    assert q.spatial.ref == "poses/two-hand-weapon.openpose.png"


def test_an_atom_without_spatial_compiles_exactly_as_before():
    """Absent stays absent: no default region, no empty Spatial. A consumer that reads
    `q.spatial is None` as "score the whole image" must keep getting None."""
    resolved = _one_atom_contract(Atom(id="skin", claim="grey-green skin", check_type=CheckType.vqa))
    q = compile_questions(resolved).by_id("skin")
    assert q.spatial is None
    assert q.model_dump(exclude_none=True).keys() == {
        "atom_id",
        "text",
        "check_type",
        "polarity",
        "severity",
    }


def test_the_spatial_pass_through_is_the_same_object_shape_the_contract_declared():
    """Not a re-derivation: the Question's spatial equals the Atom's, field for field, so a
    region-localized verifier and the contract cannot disagree about where to look."""
    spatial = Spatial(kind=SpatialKind.region, ref="chest-center")
    resolved = _one_atom_contract(
        Atom(id="sigil", claim="a triple-bar sigil", check_type=CheckType.vqa, spatial=spatial)
    )
    assert compile_questions(resolved).by_id("sigil").spatial == spatial


def test_every_shipped_example_atom_carries_its_spatial_into_the_dag(sprite_example):
    """The end-to-end pin, on the real contract: whatever the example declares, the DAG has."""
    _s, resolved, _t, _c = sprite_example
    dag = compile_questions(resolved)
    declared = {a.id: a.spatial for a in resolved.must_have}
    declared.update({m.id: m.spatial for m in resolved.must_not})
    assert {q.atom_id: q.spatial for q in dag.questions} == declared
    assert any(s is not None for s in declared.values()), "fixture declares no spatial at all"
    assert any(s is None for s in declared.values()), "fixture pins only the present case"
