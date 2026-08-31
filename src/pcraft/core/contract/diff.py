"""Atom-level delta between two resolved contracts -- what ``contract_hash()`` cannot say.

``contract_hash()`` answers *did anything change* with one opaque sha256, deliberately
all-or-nothing (its own docstring: "the same hash implies the same atom list ... the same
gate"). Nothing unpacked WHICH field moved (F-ea94c287). The consequence is already on
record: the contract-hash-drift refusal in ``receipt/asset_record.py`` "names neither hash,
neither revision, nor the contract id" -- because nothing anywhere could turn two hashes into
a readable delta. And at this system's target volume -- one faction edit propagating to every
member character, per ``loader.py``'s inheritance rule -- an author had no way to answer
"which of my six characters just gained a required atom" short of re-running ``validate`` on
each and comparing lists by eye.

WHAT THIS IS NOT:

* not a replacement for ``contract_hash()``. Receipts still need one opaque, order-independent
  fingerprint for PIN_PER_STEP; both hashes ride along in the report instead.
* not the thing that decides whether a change is a RELAXATION. That stays ``loader.py``'s
  fail-closed job. This is read-only reporting, never a gate: it has no severity opinion, it
  reports ``severity`` as one moved field among six.

The field set is imported from ``loader.py`` rather than restated, so the two cannot drift
into disagreeing about what "changed" means. Severity is added on top, because the loader
handles it in a separate arm (by rank) and a report about what moved needs both halves.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .hash import contract_hash
from .loader import _ATOM_CONTENT_FIELDS, _MUST_NOT_CONTENT_FIELDS
from .schema import ResolvedContract

ATOM_DIFF_FIELDS: tuple[str, ...] = ("severity", *_ATOM_CONTENT_FIELDS)
"""Every mutable field of an ``Atom``: the loader's content fields plus ``severity``.

Severity leads because it is the field that changes what the gate DOES with the atom; the
rest change what the atom says. ``tests/test_amend_contract.py`` pins this against
``Atom.model_fields`` so a new schema field cannot be added without teaching the diff."""

MUST_NOT_DIFF_FIELDS: tuple[str, ...] = ("severity", *_MUST_NOT_CONTENT_FIELDS)
"""The same for ``MustNot``, which has no ``depends_on``."""

_MAX_RENDERED_VALUE = 48
"""How much of a moved value ``describe()`` prints before eliding. A console line is not a
report; the full values are on the model for a caller that wants them."""


class FieldChange(BaseModel):
    """One moved field. ``before`` / ``after`` are JSON values, never pydantic models, so the
    whole report round-trips through ``json.dumps`` for a ``--json`` caller."""

    model_config = ConfigDict(extra="forbid")
    field: str
    before: Any = None
    after: Any = None


class ChangedAtom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str
    fields: list[FieldChange]


class ListDiff(BaseModel):
    """The delta for one of the two atom lists. Ids in the order they appear in their side."""

    model_config = ConfigDict(extra="forbid")
    added: list[str] = Field(default_factory=list)  # present in `right`, absent from `left`
    removed: list[str] = Field(default_factory=list)  # present in `left`, absent from `right`
    changed: list[ChangedAtom] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


class ContractDiff(BaseModel):
    """Both sides' ids and hashes, plus the per-list delta.

    The hashes are carried so a drift refusal can name BOTH sides and the delta between them
    in one object, which is the gap F-154dd9b2 recorded and could not close alone.
    """

    model_config = ConfigDict(extra="forbid")
    left_id: str
    right_id: str
    left_hash: str
    right_hash: str
    must_have: ListDiff
    must_not: ListDiff

    def is_empty(self) -> bool:
        return self.must_have.is_empty() and self.must_not.is_empty()

    def describe(self) -> list[str]:
        """Human-readable lines, ASCII, empty when nothing moved.

        ``+ id`` added, ``- id`` removed, ``~ id: field before -> after`` per moved field --
        one line each, so a six-character propagation reads as a list rather than a paragraph.
        """
        lines: list[str] = []
        for name, delta in (("must_have", self.must_have), ("must_not", self.must_not)):
            if delta.is_empty():
                continue
            lines.append(f"{name}:")
            lines.extend(f"  + {atom_id}" for atom_id in delta.added)
            lines.extend(f"  - {atom_id}" for atom_id in delta.removed)
            for atom in delta.changed:
                lines.extend(
                    f"  ~ {atom.atom_id}: {change.field} "
                    f"{_render(change.before)} -> {_render(change.after)}"
                    for change in atom.fields
                )
        return lines


def _render(value: Any) -> str:
    """One moved value as a short ASCII token. Never raises on an unexpected type."""
    try:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):  # pragma: no cover - values are JSON by construction
        text = repr(value)
    if len(text) > _MAX_RENDERED_VALUE:
        return text[: _MAX_RENDERED_VALUE - 3] + "..."
    return text


def _jsonable(value: Any) -> Any:
    """A pydantic sub-model / StrEnum as plain JSON. ``Spatial`` is the only sub-model here."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, str):  # StrEnum members are str; normalize to the bare value
        return str(value)
    return value


def _diff_one_list(left, right, fields: tuple[str, ...]) -> ListDiff:
    """By atom ID, never by position: reordering a contract's atoms is not a change to it."""
    left_by_id = {item.id: item for item in left}
    right_by_id = {item.id: item for item in right}
    changed: list[ChangedAtom] = []
    for atom_id, right_item in right_by_id.items():
        left_item = left_by_id.get(atom_id)
        if left_item is None:
            continue
        moved = [
            FieldChange(
                field=name,
                before=_jsonable(getattr(left_item, name)),
                after=_jsonable(getattr(right_item, name)),
            )
            for name in fields
            if getattr(left_item, name) != getattr(right_item, name)
        ]
        if moved:
            changed.append(ChangedAtom(atom_id=atom_id, fields=moved))
    return ListDiff(
        added=[i for i in right_by_id if i not in left_by_id],
        removed=[i for i in left_by_id if i not in right_by_id],
        changed=changed,
    )


def diff_contracts(a: ResolvedContract, b: ResolvedContract) -> ContractDiff:
    """What moved between two RESOLVED contracts, atom by atom. Pure; never raises on content.

    Resolved rather than raw, deliberately: the interesting question is "what does the GATE
    do differently now", and that is a property of the merged atom list, not of what a file
    happens to spell out versus inherit.
    """
    return ContractDiff(
        left_id=a.id,
        right_id=b.id,
        left_hash=contract_hash(a),
        right_hash=contract_hash(b),
        must_have=_diff_one_list(a.must_have, b.must_have, ATOM_DIFF_FIELDS),
        must_not=_diff_one_list(a.must_not, b.must_not, MUST_NOT_DIFF_FIELDS),
    )
