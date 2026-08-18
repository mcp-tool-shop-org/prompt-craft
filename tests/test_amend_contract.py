"""Regression tests for the wave-2 core-contract amend (swarm-1787033129-beab).

Three CRITICAL findings, all with the same shape: a fail-closed contract system that was
actually fail-OPEN at a specific seam. Each test below reproduces the exact empirical repro
from the finding, watched RED against the pre-fix source, then GREEN after the fix.

    F-38573fb8  Contract(extra="ignore") silently drops a misspelled top-level key.
    F-a5fa3f8b  A same-severity (or higher) redeclaration can silently rewrite an inherited
                atom's claim/check_type -- the "quiet" attack the loud (severity-lowering)
                guard does not catch.
    F-fb7194d3  Duplicate atom ids within one contract are never rejected, so
                QuestionDAG.topological() silently drops the second declaration.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcraft.core.contract.compile_questions import compile_questions
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


def _lookup(contracts):
    by_id = {c.id: c for c in contracts}
    return by_id.get


# ---------------------------------------------------------------------------
# F-38573fb8 -- Contract must reject unknown top-level keys (extra="forbid")
# ---------------------------------------------------------------------------


def test_contract_rejects_a_misspelled_top_level_key():
    """The exact empirical repro from the finding: 'must_have' spelled 'musthave'.

    Before the fix this parsed cleanly with must_have=[] -- a contract the author believed
    required a specific atom silently required nothing.
    """
    payload = {
        "id": "char:x",
        "level": "character",
        "extends": "faction:y",
        "musthave": [
            {"id": "sigil", "claim": "a sigil", "check_type": "vqa", "severity": "required"}
        ],
    }
    with pytest.raises(ValidationError):
        Contract.model_validate(payload)


@pytest.mark.parametrize("bad_key", ["mustnot", "extend", "levell"])
def test_contract_rejects_other_misspelled_top_level_keys(bad_key):
    payload = {"id": "char:x", "level": "character", bad_key: []}
    with pytest.raises(ValidationError):
        Contract.model_validate(payload)


def test_contract_still_matches_every_sibling_model_on_extra_forbid():
    """schema.py's own stated invariant: Contract is no longer the odd one out."""
    from pcraft.core.contract.schema import Atom as _Atom
    from pcraft.core.contract.schema import IdentityRef as _IdentityRef
    from pcraft.core.contract.schema import MustNot as _MustNot
    from pcraft.core.contract.schema import ResolvedContract as _ResolvedContract
    from pcraft.core.contract.schema import Spatial as _Spatial

    for model in (Contract, _Atom, _MustNot, _Spatial, _IdentityRef, _ResolvedContract):
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_contract_still_accepts_the_documented_note_field():
    """extra="forbid" must not re-break the '_note' field the shipped example contracts use.

    Blanket ignore -> blanket forbid is not itself the fix if it takes a legitimate,
    already-shipped authoring field down with the typos. '_note' must become a real,
    narrowly-declared field rather than tolerated extra.
    """
    contract = Contract.model_validate(
        {
            "id": "faction:x",
            "level": "faction",
            "_note": "GENERIC EXAMPLE -- not real canon.",
        }
    )
    assert contract.note == "GENERIC EXAMPLE -- not real canon."


def test_the_shipped_example_contracts_still_load():
    """Direct regression guard: both real *.contract.json fixtures use a top-level '_note'.

    This is the concrete thing that breaks if extra="forbid" ships without also declaring
    'note' -- not a hypothetical, both files under
    src/pcraft/domains/image/subdomains/sprite/contracts/ carry this key today.
    """
    from pcraft.sample import load_sprite_example

    store, resolved, _thresholds, _compiled = load_sprite_example()
    faction = store.resolve("faction:ashen-pact")
    assert faction.id == "faction:ashen-pact"
    assert resolved.id == "char:ashen-reaver"


# ---------------------------------------------------------------------------
# F-a5fa3f8b -- an inherited atom's claim/check_type are frozen; only severity may rise
# ---------------------------------------------------------------------------


def test_child_cannot_silently_rewrite_an_inherited_required_atoms_claim():
    """The finding's own repro, verbatim: 'sigil' the Iron Legion mark -> 'a plain hat',
    severity staying 'required' on both sides so the old severity-only guard never fired.
    """
    faction = Contract(
        id="faction:iron-legion",
        level="faction",
        must_have=[
            Atom(
                id="sigil",
                claim="wears the Iron Legion sigil on the chest",
                check_type=CheckType.vqa,
                severity=Severity.required,
            )
        ],
    )
    character = Contract(
        id="char:defector",
        level="character",
        extends="faction:iron-legion",
        must_have=[
            Atom(
                id="sigil",
                claim="wears a plain hat",
                check_type=CheckType.vqa,
                severity=Severity.required,
            )
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_child_cannot_rewrite_an_inherited_atoms_check_type():
    """check_type is frozen too, not just claim text -- moving an atom to a different
    verifier tier is exactly as silent a defeat as changing what it claims."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="palette", claim="ash-grey colours", check_type=CheckType.palette, severity=Severity.required)
        ],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(id="palette", claim="ash-grey colours", check_type=CheckType.vqa, severity=Severity.required)
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_raising_severity_does_not_license_a_content_swap():
    """Director's wording: 'substituting the claim is not a raise.' A child cannot launder
    a content swap by pairing it with a severity raise -- the two are independent checks."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="hat", claim="a felt hat", check_type=CheckType.vqa, severity=Severity.optional)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[Atom(id="hat", claim="a straw hat", check_type=CheckType.vqa, severity=Severity.required)],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_raising_severity_with_identical_content_is_still_allowed():
    """Regression guard: the legitimate operation the fix must not collaterally block.

    Mirrors the pre-existing test_raising_severity_is_allowed in test_contract_loader.py --
    kept here too because this file is what future work will diff against for this rule.
    """
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.optional)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.required)],
    )
    out = resolve(character, _lookup([faction, character]))
    assert out.atom_by_id("hat").severity is Severity.required
    assert out.atom_by_id("hat").claim == "a hat"


def test_child_cannot_silently_rewrite_an_inherited_must_not_claim():
    """The must_not counterpart of the finding's repro: 'a firearm of any kind' -> 'a rubber
    duck', severity=required on both sides."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_not=[MustNot(id="no_gun", claim="a firearm of any kind", severity=Severity.required)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_not=[MustNot(id="no_gun", claim="a rubber duck", severity=Severity.required)],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_must_not_raising_severity_with_identical_content_is_still_allowed():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_not=[MustNot(id="no_gun", claim="a firearm", severity=Severity.optional)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_not=[MustNot(id="no_gun", claim="a firearm", severity=Severity.required)],
    )
    out = resolve(character, _lookup([faction, character]))
    assert out.must_not[0].severity is Severity.required
    assert out.must_not[0].claim == "a firearm"


def test_contract_relaxation_from_the_loader_never_recommends_overriding_the_atom():
    """The hint text used to say 'or override the atom' -- literally endorsing the bypass
    this fix closes. errors.py's DEFAULT_HINTS is out of this domain's owned paths, but
    every CONTRACT_RELAXATION raised from loader.py is in it, and each must carry its own
    precise hint that does not recommend the thing that is now forbidden.
    """
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.required)],
    )

    # (a) severity-lowering path
    lowered = Contract(
        id="char:a", level="character", extends="faction:x",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.optional)],
    )
    with pytest.raises(PromptCraftError) as exc_a:
        resolve(lowered, _lookup([faction, lowered]))

    # (b) content-substitution path
    swapped = Contract(
        id="char:b", level="character", extends="faction:x",
        must_have=[Atom(id="hat", claim="a cap", check_type=CheckType.vqa, severity=Severity.required)],
    )
    with pytest.raises(PromptCraftError) as exc_b:
        resolve(swapped, _lookup([faction, swapped]))

    for exc in (exc_a, exc_b):
        assert "override the atom" not in exc.value.hint.lower()


# ---------------------------------------------------------------------------
# F-fb7194d3 -- duplicate atom ids within one contract must be rejected
# ---------------------------------------------------------------------------


def test_contract_rejects_duplicate_must_have_ids():
    with pytest.raises(PromptCraftError) as exc:
        Contract(
            id="char:x",
            level="character",
            must_have=[
                Atom(id="face", claim="a scarred face", check_type=CheckType.vqa),
                Atom(id="face", claim="a clean-shaven face", check_type=CheckType.vqa),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_contract_rejects_duplicate_must_not_ids():
    with pytest.raises(PromptCraftError) as exc:
        Contract(
            id="char:x",
            level="character",
            must_not=[
                MustNot(id="no_gun", claim="a pistol"),
                MustNot(id="no_gun", claim="a rifle"),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_resolved_contract_rejects_duplicate_must_not_ids():
    """The finding's own repro, constructed directly against ResolvedContract (bypassing the
    loader entirely, exactly as the audit did) -- this is the object compile_questions()
    actually consumes, so the guard must hold here even if every Contract were already clean.
    """
    with pytest.raises(PromptCraftError) as exc:
        ResolvedContract(
            id="char:x",
            level="character",
            lineage=["char:x"],
            must_have=[],
            identity_refs=[],
            must_not=[
                MustNot(id="no_gun", claim="a firearm", severity=Severity.optional),
                MustNot(id="no_gun", claim="a firearm", severity=Severity.required),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_resolved_contract_rejects_duplicate_must_have_ids():
    with pytest.raises(PromptCraftError) as exc:
        ResolvedContract(
            id="char:x",
            level="character",
            lineage=["char:x"],
            must_not=[],
            identity_refs=[],
            must_have=[
                Atom(id="face", claim="a scarred face", check_type=CheckType.vqa),
                Atom(id="face", claim="a clean face", check_type=CheckType.vqa),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_a_clean_contract_with_no_duplicates_still_compiles(sprite_example):
    """Sanity: the new guard must not false-positive on ordinary, id-unique contracts."""
    _s, resolved, _t, _c = sprite_example
    dag = compile_questions(resolved)
    ids = [q.atom_id for q in dag.questions]
    assert len(ids) == len(set(ids))


def test_distinct_ids_across_must_have_and_must_not_are_unaffected():
    """The guard is scoped to within-must_have and within-must_not, per the approved fix --
    an id used once in each list is not itself a duplicate."""
    contract = Contract(
        id="char:x",
        level="character",
        must_have=[Atom(id="face", claim="a face", check_type=CheckType.vqa)],
        must_not=[MustNot(id="no_face_paint", claim="face paint")],
    )
    assert {a.id for a in contract.must_have} == {"face"}
    assert {m.id for m in contract.must_not} == {"no_face_paint"}
