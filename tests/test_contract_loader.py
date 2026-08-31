from __future__ import annotations

import pytest

from pcraft.core.contract.loader import resolve
from pcraft.core.contract.schema import (
    Atom,
    CheckType,
    Contract,
    MustNot,
    ResolvedContract,
    Severity,
)
from pcraft.errors import PromptCraftError


def _faction(**over):
    return Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="tabard", claim="a tabard", check_type=CheckType.vqa, severity=Severity.required)],
        **over,
    )


def _lookup(contracts):
    by_id = {c.id: c for c in contracts}
    return by_id.get


def test_faction_resolves_to_itself(sprite_example):
    store, _r, _t, _c = sprite_example
    faction = store.resolve("faction:ashen-pact")
    assert faction.lineage == ["faction:ashen-pact"]
    assert {a.id for a in faction.must_have} == {"tabard", "sigil", "palette"}


def test_character_inherits_and_composes_identity(sprite_example):
    _store, resolved, _t, _c = sprite_example
    # character resolves with faction atoms + its own
    ids = {a.id for a in resolved.must_have}
    assert {"tabard", "sigil", "palette"} <= ids  # inherited
    assert {"skin", "weapon", "face"} <= ids  # own
    assert resolved.lineage == ["faction:ashen-pact", "char:ashen-reaver"]
    # identity composes: faction costume plate + character face plate
    assert len(resolved.identity_refs) == 2
    scopes = {ir.scope for ir in resolved.identity_refs}
    assert scopes == {"costume", "face"}


def test_relaxing_a_faction_required_atom_is_fail_closed():
    faction = _faction()
    character = Contract(
        id="char:y", level="character", extends="faction:x",
        must_have=[Atom(id="tabard", claim="a tabard", check_type=CheckType.vqa, severity=Severity.optional)],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_raising_severity_is_allowed():
    faction = Contract(
        id="faction:x", level="faction",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.optional)],
    )
    character = Contract(
        id="char:y", level="character", extends="faction:x",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.required)],
    )
    out = resolve(character, _lookup([faction, character]))
    assert out.atom_by_id("hat").severity is Severity.required


def test_dropping_a_required_atom_keeps_it_inherited():
    faction = _faction()
    character = Contract(id="char:y", level="character", extends="faction:x", must_have=[])
    out = resolve(character, _lookup([faction, character]))
    assert out.atom_by_id("tabard") is not None  # not silently droppable


def test_missing_base_raises():
    character = Contract(id="char:y", level="character", extends="faction:nope", must_have=[])
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([character]))
    assert exc.value.code == "CONTRACT_MISSING_BASE"


# ---------------------------------------------------------------------------
# F-19f97de2 -- depends_on is REFERENTIAL and must name an atom that exists
#
# The loader already refuses a dangling `extends` (CONTRACT_MISSING_BASE) and a duplicate
# atom id (CONTRACT_DUPLICATE_ATOM_ID), but nothing checked that `depends_on` resolves. A
# typo'd parent silently demoted its atom to a ROOT: QuestionDAG.topological()'s
# `if q.depends_on and q.depends_on in index` skips the unknown edge, so the atom is
# evaluated unconditionally and the "a NO parent forces NO on descendants" guarantee -- the
# entire reason depends_on exists -- quietly does not apply to it. Load time is the right
# door: the contract, not the gate run, is where the reference is wrong.
# ---------------------------------------------------------------------------


def test_a_dangling_depends_on_is_refused_at_load():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="face", claim="a face", check_type=CheckType.vqa),
            Atom(id="scar", claim="a scar", check_type=CheckType.vqa, depends_on="fcae"),
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(faction, _lookup([faction]))
    assert exc.value.code == "CONTRACT_UNKNOWN_DEPENDS_ON"


def test_a_dangling_depends_on_names_the_atom_and_the_missing_parent():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="scar", claim="a scar", check_type=CheckType.vqa, depends_on="ghost")],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(faction, _lookup([faction]))
    assert "scar" in exc.value.message
    assert "ghost" in exc.value.message
    assert exc.value.exit_code == 1


def test_an_intact_depends_on_still_resolves():
    """The collateral guard. The shipped faction contract uses depends_on today."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="face", claim="a face", check_type=CheckType.vqa),
            Atom(id="scar", claim="a scar", check_type=CheckType.vqa, depends_on="face"),
        ],
    )
    out = resolve(faction, _lookup([faction]))
    assert out.atom_by_id("scar").depends_on == "face"


def test_the_shipped_example_contracts_still_resolve(sprite_example):
    """The real fixture carries a live depends_on edge; the new check must not refuse it."""
    store, resolved, _t, _c = sprite_example
    assert store.resolve("faction:ashen-pact").atom_by_id("sigil").depends_on == "tabard"
    assert resolved.atom_by_id("sigil").depends_on == "tabard"


def test_a_character_may_depend_on_an_inherited_faction_atom():
    """The false-positive this check must not produce. A character's own must_have list does
    not contain the faction's atoms, so the referential check has to run on the MERGED
    contract -- never on the raw child in isolation."""
    faction = _faction()  # declares must_have=[tabard]
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(id="sigil", claim="a sigil", check_type=CheckType.vqa, depends_on="tabard")
        ],
    )
    out = resolve(character, _lookup([faction, character]))
    assert out.atom_by_id("sigil").depends_on == "tabard"
    assert out.atom_by_id("tabard") is not None


def test_a_character_introducing_a_dangling_depends_on_is_refused():
    faction = _faction()
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(id="sigil", claim="a sigil", check_type=CheckType.vqa, depends_on="tabbard")
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_UNKNOWN_DEPENDS_ON"


def test_a_redeclared_inherited_atom_keeping_its_intact_depends_on_still_resolves():
    """Inherited-atom redeclaration: a severity raise restating the SAME depends_on is legal
    and must survive the referential check as well as the relaxation guard."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="face", claim="a face", check_type=CheckType.vqa, severity=Severity.optional),
            Atom(
                id="scar",
                claim="a scar",
                check_type=CheckType.vqa,
                severity=Severity.optional,
                depends_on="face",
            ),
        ],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(
                id="scar",
                claim="a scar",
                check_type=CheckType.vqa,
                severity=Severity.required,
                depends_on="face",
            )
        ],
    )
    out = resolve(character, _lookup([faction, character]))
    assert out.atom_by_id("scar").severity is Severity.required
    assert out.atom_by_id("scar").depends_on == "face"


def test_a_depends_on_pointing_at_a_must_not_id_is_accepted():
    """compile_questions indexes must_have AND must_not into one DAG keyed by atom_id, so a
    negation id is a resolvable parent. The check must mirror the DAG's real index, not a
    narrower guess -- refusing this would be a false positive."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="clean", claim="clean skin", check_type=CheckType.vqa, depends_on="no_scar")],
        must_not=[MustNot(id="no_scar", claim="a scar")],
    )
    out = resolve(faction, _lookup([faction]))
    assert out.atom_by_id("clean").depends_on == "no_scar"


def test_an_empty_string_depends_on_is_refused_not_silently_treated_as_a_root():
    """`depends_on: ""` is a typo, not "no parent". The DAG's `if q.depends_on and ...` guard
    reads it as falsy and drops the edge without a word."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="scar", claim="a scar", check_type=CheckType.vqa, depends_on="")],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(faction, _lookup([faction]))
    assert exc.value.code == "CONTRACT_UNKNOWN_DEPENDS_ON"


# ---------------------------------------------------------------------------
# F-877a8d9b -- the referential check belongs to the TYPE, not to resolve()
#
# The check above shipped as an imperative call inside loader.resolve(), which made the
# invariant a property of ONE code path. MEASURED before the move: a ResolvedContract built
# directly with depends_on="ghost" constructed with zero error, while the identical
# direct-construction style with a duplicate id raised CONTRACT_DUPLICATE_ATOM_ID
# immediately -- because THAT guard was a @model_validator. The live blast radius was zero
# (every production caller reaches the DAG through harness.evaluate, whose own
# `verdicts.get(parent) is None -> SKIPPED` arm is the other half of F-19f97de2), but
# optimize/compile.py's GateMetric takes list[ResolvedContract], so a programmatically
# assembled trainset is a concrete caller that never touches ContractStore.
# ---------------------------------------------------------------------------


def test_a_directly_built_resolved_contract_refuses_a_dangling_depends_on():
    """The finding's own repro, bypassing the loader exactly as the audit did."""
    with pytest.raises(PromptCraftError) as exc:
        ResolvedContract(
            id="char:probe",
            level="character",
            lineage=["char:probe"],
            identity_refs=[],
            must_not=[],
            must_have=[
                Atom(id="face", claim="a face", check_type=CheckType.vqa),
                Atom(id="scar", claim="a scar", check_type=CheckType.vqa, depends_on="ghost"),
            ],
        )
    assert exc.value.code == "CONTRACT_UNKNOWN_DEPENDS_ON"
    assert "ghost" in exc.value.message


def test_a_directly_built_resolved_contract_with_intact_edges_still_constructs():
    """The collateral guard: moving the check onto the type must not refuse a valid object."""
    out = ResolvedContract(
        id="char:probe",
        level="character",
        lineage=["char:probe"],
        identity_refs=[],
        must_not=[],
        must_have=[
            Atom(id="face", claim="a face", check_type=CheckType.vqa),
            Atom(id="scar", claim="a scar", check_type=CheckType.vqa, depends_on="face"),
        ],
    )
    assert out.atom_by_id("scar").depends_on == "face"


# ---------------------------------------------------------------------------
# F-2b317b56 -- a depends_on CYCLE is refused at load, under a named code
#
# The dangling edge was one way a dependency graph can be unusable; a cycle is the other, and
# nothing refused it where an author would meet it. MEASURED before this fix: a 2-cycle
# contract passed `pcraft validate` with "ok" and exit 0 -- validate compiles the DAG but
# never walks it -- and then died in bind/gate with a bare ValueError out of
# QuestionDAG.topological(), which the CLI backstop reports as RUNTIME_UNEXPECTED (exit 2,
# "prompt-craft crashed") for what is really a malformed contract (exit 1, "fix your input").
# A self-edge behaved identically: it passes the referential check, because the id IS present.
# ---------------------------------------------------------------------------


def test_a_two_atom_depends_on_cycle_is_refused_at_load():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="a", claim="an a", check_type=CheckType.vqa, depends_on="b"),
            Atom(id="b", claim="a b", check_type=CheckType.vqa, depends_on="a"),
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(faction, _lookup([faction]))
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"
    assert exc.value.exit_code == 1
    assert "a -> b -> a" in exc.value.message


def test_a_self_depending_atom_is_refused_at_load():
    """The referential check cannot catch this one: the parent id IS present -- it is the
    atom's own. Only an acyclicity check refuses it."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="scar", claim="a scar", check_type=CheckType.vqa, depends_on="scar")],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(faction, _lookup([faction]))
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"
    assert "scar -> scar" in exc.value.message


def test_a_cycle_reached_through_an_acyclic_tail_is_still_refused():
    """A loop no single atom's own edge closes: tail -> a -> b -> a. The refusal names the
    cycle, not the road into it."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="tail", claim="a tail", check_type=CheckType.vqa, depends_on="a"),
            Atom(id="a", claim="an a", check_type=CheckType.vqa, depends_on="b"),
            Atom(id="b", claim="a b", check_type=CheckType.vqa, depends_on="a"),
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(faction, _lookup([faction]))
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"
    assert "tail" not in exc.value.message


def test_a_cycle_introduced_across_the_inheritance_merge_is_refused():
    """The character closes a loop among atoms it adds, so only the POST-merge lists show it
    -- the same reason the referential check runs after the merge."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="tabard", claim="a tabard", check_type=CheckType.vqa)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(id="sigil", claim="a sigil", check_type=CheckType.vqa, depends_on="crest"),
            Atom(id="crest", claim="a crest", check_type=CheckType.vqa, depends_on="sigil"),
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"


def test_a_directly_built_resolved_contract_refuses_a_cycle():
    """Same invariant, on the type -- the construction path a GEPA trainset would take."""
    with pytest.raises(PromptCraftError) as exc:
        ResolvedContract(
            id="char:cyc",
            level="character",
            lineage=["char:cyc"],
            identity_refs=[],
            must_not=[],
            must_have=[
                Atom(id="a", claim="an a", check_type=CheckType.vqa, depends_on="b"),
                Atom(id="b", claim="a b", check_type=CheckType.vqa, depends_on="a"),
            ],
        )
    assert exc.value.code == "CONTRACT_CYCLIC_DEPENDS_ON"


def test_an_intact_depends_on_chain_still_loads():
    """The collateral guard for the cycle check: a long acyclic chain is not a loop, and an
    edge into must_not is a legal parent (compile_questions indexes one id namespace)."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="face", claim="a face", check_type=CheckType.vqa),
            Atom(id="scar", claim="a scar", check_type=CheckType.vqa, depends_on="face"),
            Atom(id="stitch", claim="a stitch", check_type=CheckType.vqa, depends_on="scar"),
            Atom(id="clean", claim="clean skin", check_type=CheckType.vqa, depends_on="no_dirt"),
        ],
        must_not=[MustNot(id="no_dirt", claim="dirt")],
    )
    out = resolve(faction, _lookup([faction]))
    assert out.atom_by_id("stitch").depends_on == "scar"
    assert out.atom_by_id("clean").depends_on == "no_dirt"


def test_the_shipped_example_contracts_are_still_acyclic(sprite_example):
    """The real fixture carries a live depends_on edge; the cycle check must not refuse it."""
    store, resolved, _t, _c = sprite_example
    assert store.resolve("faction:ashen-pact").atom_by_id("sigil").depends_on == "tabard"
    assert resolved.atom_by_id("sigil").depends_on == "tabard"
