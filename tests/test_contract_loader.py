from __future__ import annotations

import pytest

from pcraft.core.contract.loader import resolve
from pcraft.core.contract.schema import Atom, CheckType, Contract, Severity
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
    store, resolved, _t, _c = sprite_example
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
