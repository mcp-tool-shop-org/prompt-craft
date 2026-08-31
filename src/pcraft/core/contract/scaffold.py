"""Build a NEW contract from named inputs -- the authoring on-ramp (F-a9d86551).

Before this module, authoring a ``*.contract.json`` started by copying one of the two shipped
examples by hand. MEASURED: a grep across ``src/pcraft/`` and ``tests/`` for
``scaffold|new_contract|interview|new-contract`` returned zero contract-authoring hits, and
none of the CLI's twelve commands writes a contract -- ``pcraft schema`` emits the JSON Schema
for validation but does not fill it in. So the on-ramp was: hand-edit ``extra="forbid"``
pydantic models with no field-level feedback until CONTRACT_INVALID fires on save. At the
volume this domain is built for -- one faction composing many characters, per ``loader.py``'s
inheritance model -- that is the highest-friction step in the pipeline by the third character.

THE PROOF OBLIGATION, and the reason this is a library function rather than a template
string: what comes out must load back through the SAME ``_read_contract`` / ``resolve()`` path
a hand-written file takes. Never a shortcut around the relaxation, duplicate-id or cycle
checks. ``scaffold_contract`` builds a real ``Contract``, so every schema validator and the
duplicate-id ``@model_validator`` run at construction; ``scaffold_json`` emits the on-disk
form of that same object.

WHAT IS NOT HERE, deliberately: the CLI verb (``pcraft new``) and any interactive loop belong
to the CLI surface, exactly as FEAT-005's ``ids()`` / ``source_path()`` shipped as library
methods that ``pcraft doctor`` later called.

    from pcraft.core.contract.scaffold import (
        DEFAULT_CHECK_TYPE,   # CheckType.vqa -- what a starter atom gets when none is named
        LEVELS,               # ("faction", "character")
        inherited_atom_ids,   # (store, base_id) -> list[str]
        scaffold_atom,        # (atom_id, claim, **overrides) -> Atom
        scaffold_contract,    # (level, contract_id, **named inputs) -> Contract
        scaffold_json,        # (contract) -> str, the exact on-disk text
        scaffold_must_not,    # (atom_id, claim, **overrides) -> MustNot
    )
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ...errors import PromptCraftError
from .loader import ContractStore, describe_validation_error
from .schema import (
    CONTRACT_SCHEMA_ID,
    Atom,
    CheckType,
    Contract,
    IdentityRef,
    MustNot,
)

FACTION = "faction"
CHARACTER = "character"
LEVELS: tuple[str, str] = (FACTION, CHARACTER)
"""The two levels ``loader._walk_extends`` actually acts on.

``Contract.level`` is a bare ``str`` on the schema, so ``"charcter"`` constructs happily --
and then behaves as a faction, because the walk's condition is ``level != "faction"``: the
typo'd contract's ``extends`` is silently never followed. That is a silent-drop defect of
exactly the class this package refuses everywhere else, so the scaffold refuses it here."""

DEFAULT_CHECK_TYPE = CheckType.vqa
"""What a starter atom gets when the caller names none.

``Atom.check_type`` is REQUIRED on the schema (no default), while ``MustNot.check_type``
defaults to ``vqa``. The scaffold uses the same value for both, so a starter atom lands on the
compositional tier -- the one that can verify an arbitrary claim -- rather than on a closed-set
or deterministic tier the author has not set up yet."""

_ATOM_KEYS = frozenset(Atom.model_fields)
_MUST_NOT_KEYS = frozenset(MustNot.model_fields)


def scaffold_atom(atom_id: str, claim: str, **overrides: Any) -> Atom:
    """One ``must_have`` atom with the schema's defaults filled in. Overrides pass through."""
    return Atom(id=atom_id, claim=claim, **{"check_type": DEFAULT_CHECK_TYPE, **overrides})


def scaffold_must_not(atom_id: str, claim: str, **overrides: Any) -> MustNot:
    """One ``must_not`` atom. ``MustNot`` already defaults ``check_type``; this is the pair to
    ``scaffold_atom`` so a caller does not have to remember which of the two needs help."""
    return MustNot(id=atom_id, claim=claim, **overrides)


def inherited_atom_ids(store: ContractStore, base_id: str) -> list[str]:
    """Every atom id a contract extending ``base_id`` would inherit, must_have first.

    READ VIA THE STORE, never hand-typed: an interview loop can show these, and
    ``scaffold_contract`` uses them to refuse a starter atom that would collide.
    """
    resolved = store.resolve(base_id)
    return [a.id for a in resolved.must_have] + [m.id for m in resolved.must_not]


def _coerce(value: Any, *, model, keys: frozenset[str], factory, where: str):
    """One starter atom, from any of the three accepted forms.

    An already-built model passes through; a ``(id, claim)`` pair is the terse interview form;
    a mapping is what a JSON-shaped caller (a CLI flag, a domain's content-aware layer)
    produces. Anything else is refused rather than coerced -- guessing here would produce a
    contract the author did not write.
    """
    if isinstance(value, model):
        return value
    if isinstance(value, Mapping):
        unknown = set(value) - keys
        if unknown:
            raise PromptCraftError(
                "INPUT_SCAFFOLD_ATOM_FORM",
                f"{where} mapping carries unknown key(s) {sorted(unknown)}",
                hint=(
                    f"A {model.__name__} accepts {sorted(keys)}. The contract schema is "
                    "extra=forbid, so an unknown key would be refused at load time anyway -- "
                    "this says so while the value is still in your hands."
                ),
            )
        data = {"check_type": DEFAULT_CHECK_TYPE, **value}
        return model(**data)
    if isinstance(value, tuple | list) and len(value) == 2:
        return factory(str(value[0]), str(value[1]))
    raise PromptCraftError(
        "INPUT_SCAFFOLD_ATOM_FORM",
        f"cannot read {where} from {type(value).__name__}",
        hint=(
            f"A starter atom is a {model.__name__}, an (id, claim) pair, or a mapping of "
            "field names. Those are the three forms; anything else would have to be guessed at."
        ),
    )


def _coerce_all(values: Sequence[Any] | None, *, model, keys, factory, where: str) -> list:
    return [
        _coerce(value, model=model, keys=keys, factory=factory, where=f"{where}[{index}]")
        for index, value in enumerate(values or ())
    ]


def scaffold_contract(
    level: str,
    contract_id: str,
    *,
    extends: str | None = None,
    must_have: Sequence[Any] | None = None,
    must_not: Sequence[Any] | None = None,
    identity_plate: str | None = None,
    identity_scope: str = "face",
    note: str | None = None,
    store: ContractStore | None = None,
) -> Contract:
    """A valid, minimal ``Contract`` from named inputs. Round-trips through the real loader.

    ``level`` is ``"faction"`` or ``"character"``; ``contract_id`` is the id the store indexes
    by (``faction:ashen-pact``, ``char:ashen-reaver``). ``must_have`` / ``must_not`` each accept
    a sequence of ``Atom``/``MustNot`` objects, ``(id, claim)`` pairs, or mappings -- see
    ``_coerce``. ``store``, when given, is what turns ``extends`` from a string into a checked
    reference: the base must exist, and no starter atom may collide with an inherited id.

    Refuses, all exit 1:

    * ``INPUT_SCAFFOLD_LEVEL`` -- a level the loader cannot act on (see ``LEVELS``).
    * ``INPUT_SCAFFOLD_FACTION_EXTENDS`` -- a faction that declares ``extends``. The walk stops
      on ``level == "faction"`` BEFORE reading the field, so such a contract inherits nothing
      and is told nothing about it.
    * ``INPUT_SCAFFOLD_INHERITED_ID`` -- a starter atom reusing an id the base already declares.
      At load time that is CONTRACT_RELAXATION, a refusal about relaxation for what is really a
      name collision; said here, the author can still pick another id.
    * ``INPUT_SCAFFOLD_ATOM_FORM`` -- a starter atom in a form this function will not guess at.
    * ``INPUT_SCAFFOLD_INVALID`` -- the schema refused the result. This is a library entry point
      like ``_read_contract``, so it owes the same structured refusal rather than letting a raw
      pydantic ``ValidationError`` cross the boundary.

    Guards this function does NOT own: duplicate ids inside one contract, ``depends_on``
    integrity and every relaxation rule. Those live on the models and in ``resolve()``, and
    they run here because this builds a real ``Contract`` -- never around them.
    """
    if level not in LEVELS:
        raise PromptCraftError(
            "INPUT_SCAFFOLD_LEVEL",
            f"level {level!r} is not one of {list(LEVELS)}",
            hint=(
                "A contract is a faction (the inheritable base) or a character (which extends "
                "one). The loader follows `extends` only when level is not 'faction', so a "
                "misspelled level silently disables inheritance instead of failing."
            ),
        )
    if level == FACTION and extends is not None:
        raise PromptCraftError(
            "INPUT_SCAFFOLD_FACTION_EXTENDS",
            f"faction {contract_id!r} declares extends {extends!r}, which nothing will follow",
            hint=(
                "A faction is the base class -- the extends walk terminates on it before the "
                "field is read. Make this a character to inherit from another contract, or "
                "drop the extends."
            ),
        )

    # ONE handler over the whole build, not just the Contract(...) line: a blank id in a
    # starter atom fails while the Atom is constructed, several frames before the contract
    # exists, and that ValidationError would otherwise cross this boundary raw -- the exact
    # defect _read_contract closed for the on-disk path (F-45c39f7d).
    try:
        atoms = _coerce_all(
            must_have, model=Atom, keys=_ATOM_KEYS, factory=scaffold_atom, where="must_have"
        )
        negations = _coerce_all(
            must_not,
            model=MustNot,
            keys=_MUST_NOT_KEYS,
            factory=scaffold_must_not,
            where="must_not",
        )
        if store is not None and extends is not None:
            _reject_inherited_collisions(store, extends, atoms, negations, contract_id=contract_id)
        return Contract(
            **{"$schema": CONTRACT_SCHEMA_ID},
            id=contract_id,
            level=level,
            extends=extends,
            must_have=atoms,
            must_not=negations,
            identity_ref=(
                IdentityRef(plate=identity_plate, scope=identity_scope)
                if identity_plate is not None
                else None
            ),
            **({"_note": note} if note is not None else {}),
        )
    except PromptCraftError:
        # A guard inside a @model_validator (duplicate atom ids) already speaks the structured
        # shape and carries a precise code. Pass it through untouched, exactly as
        # loader._read_contract does -- the scaffold must not restate the loader's refusals.
        raise
    except ValidationError as err:
        raise PromptCraftError(
            "INPUT_SCAFFOLD_INVALID",
            f"scaffolded contract {contract_id!r} does not match the contract schema: "
            f"{describe_validation_error(err)}",
            hint=(
                "Fix the field(s) the message names. `pcraft schema` dumps the authoring JSON "
                "Schema, and the same refusal would have fired on the file at load time."
            ),
            cause=err,
        ) from err


def _reject_inherited_collisions(
    store: ContractStore,
    extends: str,
    atoms: Sequence[Atom],
    negations: Sequence[MustNot],
    *,
    contract_id: str,
) -> None:
    inherited = set(inherited_atom_ids(store, extends))
    declared: tuple[Atom | MustNot, ...] = (*atoms, *negations)
    collisions = sorted({item.id for item in declared} & inherited)
    if collisions:
        raise PromptCraftError(
            "INPUT_SCAFFOLD_INHERITED_ID",
            f"{contract_id!r} declares starter atom(s) {collisions} that {extends!r} "
            f"already provides",
            hint=(
                "An inherited id may be RESTATED only to raise its severity -- restating it "
                "with new content is CONTRACT_RELAXATION at load time. Give the new atom its "
                "own id; the inherited one carries through automatically."
            ),
        )


def scaffold_json(contract: Contract) -> str:
    """The exact on-disk text for a contract. ASCII, two-space indent, newline-terminated.

    Aliases are applied (``$schema``, ``_note``) and ``None`` fields are omitted, so the output
    reads like the shipped examples rather than like a dump full of nulls -- and so an optional
    field left unset stays unset rather than being written as an explicit null that an
    inheriting contract would then be comparing against.

    ASCII by the same doctrine as ``pcraft schema``: this text is written to a file AND printed
    to a console whose codepage we do not control.
    """
    payload = contract.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
