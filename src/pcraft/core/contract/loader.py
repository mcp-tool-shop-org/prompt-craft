"""Contract loader: resolves ``extends`` (faction -> character), FAIL-CLOSED.

The single load-bearing rule (from sdlab identity inheritance): a character may **raise** a
severity or add atoms, but may **never drop a faction-required atom, relax its severity, or
rewrite its claim/check_type** while keeping its id. The loader throws
``PromptCraftError(CONTRACT_RELAXATION)`` if it tries. One edit to a faction contract then
propagates to every member's gate automatically."""

from __future__ import annotations

import json
from pathlib import Path

from ...errors import PromptCraftError
from .schema import Contract, IdentityRef, ResolvedContract, Severity


class ContractStore:
    """Loads contracts by id from a directory tree of ``*.contract.json`` files.

    The store indexes by the contract's ``id`` field (e.g. ``faction:ashen-pact``), so ``extends``
    resolves by reference regardless of file layout."""

    def __init__(self, roots: list[Path]):
        self._by_id: dict[str, Contract] = {}
        self._source: dict[str, Path] = {}
        for root in roots:
            for path in sorted(Path(root).rglob("*.contract.json")):
                contract = _read_contract(path)
                if contract.id in self._by_id:
                    raise PromptCraftError(
                        "INPUT_DUPLICATE_CONTRACT_ID",
                        f"contract id {contract.id!r} defined twice: "
                        f"{self._source[contract.id]} and {path}",
                    )
                self._by_id[contract.id] = contract
                self._source[contract.id] = path

    def get(self, contract_id: str) -> Contract:
        if contract_id not in self._by_id:
            raise PromptCraftError(
                "INPUT_UNKNOWN_CONTRACT",
                f"no contract with id {contract_id!r} found in the store",
                hint="Check the id spelling, or add the contract file to the store roots.",
            )
        return self._by_id[contract_id]

    def resolve(self, contract_id: str) -> ResolvedContract:
        return resolve(self.get(contract_id), self._by_id.get)


def _read_contract(path: Path) -> Contract:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise PromptCraftError("IO_CONTRACT_READ", f"could not read contract {path}", cause=err) from err
    return Contract.model_validate(data)


def resolve(contract: Contract, lookup) -> ResolvedContract:
    """Merge a contract with its faction base. ``lookup(id) -> Contract | None``.

    A faction resolves to itself. A character merges its faction base then its own atoms,
    enforcing the no-relaxation rule."""
    if contract.level == "faction" or contract.extends is None:
        return ResolvedContract(
            id=contract.id,
            level=contract.level,
            lineage=[contract.id],
            must_have=list(contract.must_have),
            must_not=list(contract.must_not),
            identity_refs=[contract.identity_ref] if contract.identity_ref else [],
        )

    base_contract = lookup(contract.extends)
    if base_contract is None:
        raise PromptCraftError(
            "CONTRACT_MISSING_BASE",
            f"{contract.id!r} extends {contract.extends!r} but that faction is not in the store",
        )
    base = resolve(base_contract, lookup)  # recurse: support multi-level chains

    merged_must_have = _merge_atoms_fail_closed(base.must_have, contract.must_have, child_id=contract.id)
    merged_must_not = _merge_must_not(base.must_not, contract.must_not, child_id=contract.id)
    identity_refs: list[IdentityRef] = list(base.identity_refs)
    if contract.identity_ref:
        identity_refs.append(contract.identity_ref)

    return ResolvedContract(
        id=contract.id,
        level=contract.level,
        lineage=[*base.lineage, contract.id],
        must_have=merged_must_have,
        must_not=merged_must_not,
        identity_refs=identity_refs,
    )


_SEVERITY_RANK = {Severity.optional: 0, Severity.required: 1}


_RELAXATION_HINT = (
    "A character contract may not drop or relax a faction-required atom, and may not "
    "rewrite an inherited atom's claim or check_type while keeping its id. Raise the "
    "severity, or add a new id for genuinely different content — never substitute an "
    "existing id's content."
)


def _merge_atoms_fail_closed(base_atoms, child_atoms, *, child_id: str):
    """Union by atom id. A child override may only RAISE severity, never lower it — and may
    never rewrite an inherited id's claim/check_type, at any severity (F-a5fa3f8b): raising
    severity is not a licence to also substitute what the atom checks for."""
    by_id = {a.id: a for a in base_atoms}
    child_ids = {a.id for a in child_atoms}

    for atom in child_atoms:
        base_atom = by_id.get(atom.id)
        if base_atom is not None:
            if _SEVERITY_RANK[atom.severity] < _SEVERITY_RANK[base_atom.severity]:
                raise PromptCraftError(
                    "CONTRACT_RELAXATION",
                    f"character {child_id!r} relaxes faction atom {atom.id!r} "
                    f"({base_atom.severity.value} -> {atom.severity.value})",
                    hint=_RELAXATION_HINT,
                )
            if atom.claim != base_atom.claim or atom.check_type != base_atom.check_type:
                raise PromptCraftError(
                    "CONTRACT_RELAXATION",
                    f"character {child_id!r} rewrites faction atom {atom.id!r}'s content "
                    f"(claim {base_atom.claim!r} -> {atom.claim!r}, "
                    f"check_type {base_atom.check_type.value!r} -> {atom.check_type.value!r}); "
                    "substituting the claim is not a raise",
                    hint=_RELAXATION_HINT,
                )
        by_id[atom.id] = atom  # override (same severity/claim/check_type, or a genuine raise) or add

    # A character cannot silently DROP a faction-required atom: it simply isn't in child_ids,
    # so the base version survives the union above. That is the fail-closed default — inherited
    # required atoms always carry through, and (per the content-freeze check above) they carry
    # through UNCHANGED: a redeclared id may raise severity but never rewrite claim/check_type.
    # (Documented here because the *absence* is the guarantee.)
    del child_ids  # (kept for readability of the invariant; not used)
    # Preserve base order, then append child-only atoms in declared order.
    ordered = [by_id[a.id] for a in base_atoms]
    for atom in child_atoms:
        if atom.id not in {b.id for b in base_atoms}:
            ordered.append(by_id[atom.id])
    return ordered


def _merge_must_not(base, child, *, child_id: str):
    """Union by id, fail-closed on severity — the same rule ``_merge_atoms_fail_closed`` enforces.

    ⚑ This guard was ADDED when ``MustNot`` gained a severity, and it closes a hole that change
    opened. Before the field existed every negation was required by construction, so a plain
    override could not relax anything and none was needed. The moment a negation can be
    ``optional``, a character contract could override an inherited ``required`` negation down to
    ``optional`` and the loader would allow it — silently relaxing the exact kind of inherited
    requirement this module exists to protect.

    Measured before the fix: a faction declaring ``no_gun`` required and a character re-declaring
    it optional resolved to optional, no error.

    ⚑ SECOND GUARD, same finding (F-a5fa3f8b). Severity-lowering was the *loud* attack; a child
    could still keep ``no_gun``'s id and severity while rewriting its claim from "a firearm" to
    "a rubber duck" — same blocking power, different (or no) actual constraint. Claim/check_type
    are now frozen on a redeclared id, exactly as for ``must_have`` in ``_merge_atoms_fail_closed``.
    """
    by_id = {m.id: m for m in base}
    for m in child:
        base_mn = by_id.get(m.id)
        if base_mn is not None:
            if _SEVERITY_RANK[m.severity] < _SEVERITY_RANK[base_mn.severity]:
                raise PromptCraftError(
                    "CONTRACT_RELAXATION",
                    f"character {child_id!r} relaxes faction must_not {m.id!r} "
                    f"({base_mn.severity.value} -> {m.severity.value})",
                    hint=_RELAXATION_HINT,
                )
            if m.claim != base_mn.claim or m.check_type != base_mn.check_type:
                raise PromptCraftError(
                    "CONTRACT_RELAXATION",
                    f"character {child_id!r} rewrites faction must_not {m.id!r}'s content "
                    f"(claim {base_mn.claim!r} -> {m.claim!r}, "
                    f"check_type {base_mn.check_type.value!r} -> {m.check_type.value!r}); "
                    "substituting the claim is not a raise",
                    hint=_RELAXATION_HINT,
                )
        by_id[m.id] = m
    return list(by_id.values())
