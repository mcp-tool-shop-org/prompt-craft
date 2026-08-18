"""Contract loader: resolves ``extends`` (faction -> character), FAIL-CLOSED.

The single load-bearing rule (from sdlab identity inheritance): a character may **raise** a
severity or add atoms, but may **never drop a faction-required atom, relax its severity, or
rewrite its content (claim, check_type, spatial, enum, depends_on)** while keeping its id. The loader throws
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

    def ids(self) -> list[str]:
        return sorted(self._by_id)

    def source_path(self, contract_id: str) -> Path:
        self.get(contract_id)
        return self._source[contract_id]

    def get(self, contract_id: str) -> Contract:
        if contract_id not in self._by_id:
            raise PromptCraftError(
                "INPUT_UNKNOWN_CONTRACT",
                f"no contract with id {contract_id!r} found in the store",
                hint="Check the id spelling, or pass --contracts-dir at the tree that holds it.",
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
    identity_refs = _merge_identity_refs(
        base.identity_refs, contract.identity_ref, child_id=contract.id
    )

    return ResolvedContract(
        id=contract.id,
        level=contract.level,
        lineage=[*base.lineage, contract.id],
        must_have=merged_must_have,
        must_not=merged_must_not,
        identity_refs=identity_refs,
    )


def _merge_identity_refs(
    base_refs: list[IdentityRef], child_ref: IdentityRef | None, *, child_id: str
) -> list[IdentityRef]:
    """Compose different plates; refuse a same-plate rewrite that drops the lock.

    Faction costume + character face is the documented composition. A child that
    restates an inherited plate may only raise weight. Changing method or scope,
    or lowering weight (including method=none / weight=0), is CONTRACT_RELAXATION.
    """
    if child_ref is None:
        return list(base_refs)
    merged = list(base_refs)
    for i, existing in enumerate(merged):
        if existing.plate != child_ref.plate:
            continue
        if child_ref.method != existing.method or child_ref.scope != existing.scope:
            raise PromptCraftError(
                "CONTRACT_RELAXATION",
                f"character {child_id!r} rewrites inherited identity plate "
                f"{existing.plate!r} (method {existing.method!r}->{child_ref.method!r}, "
                f"scope {existing.scope!r}->{child_ref.scope!r})",
                hint=_RELAXATION_HINT,
            )
        if child_ref.weight < existing.weight:
            raise PromptCraftError(
                "CONTRACT_RELAXATION",
                f"character {child_id!r} lowers inherited identity weight on "
                f"{existing.plate!r} ({existing.weight} -> {child_ref.weight})",
                hint=_RELAXATION_HINT,
            )
        merged[i] = existing.model_copy(update={"weight": child_ref.weight})
        return merged
    merged.append(child_ref)
    return merged


_SEVERITY_RANK = {Severity.optional: 0, Severity.required: 1}


_RELAXATION_HINT = (
    "A character contract may not drop or relax a faction-required atom, and may not "
    "rewrite an inherited atom's claim, check_type, spatial, enum, or depends_on, "
    "or neutralize an inherited identity plate. Raise the severity or weight, or add "
    "a new id or plate — never substitute an existing id's content."
)


def _rewritten_atom_fields(base, child) -> list[str]:
    """Content fields the child restated differently from the inherited atom.

    Omitted optional fields (spatial/enum/depends_on left at None) inherit the base.
    An explicit different value is a rewrite. claim and check_type are always stated.
    """
    changed: list[str] = []
    if child.claim != base.claim:
        changed.append("claim")
    if child.check_type != base.check_type:
        changed.append("check_type")
    if child.spatial is not None and child.spatial != base.spatial:
        changed.append("spatial")
    if child.enum is not None and child.enum != base.enum:
        changed.append("enum")
    if child.depends_on is not None and child.depends_on != base.depends_on:
        changed.append("depends_on")
    return changed


def _rewritten_must_not_fields(base, child) -> list[str]:
    changed: list[str] = []
    if child.claim != base.claim:
        changed.append("claim")
    if child.check_type != base.check_type:
        changed.append("check_type")
    if child.enum is not None and child.enum != base.enum:
        changed.append("enum")
    if child.spatial is not None and child.spatial != base.spatial:
        changed.append("spatial")
    return changed


def _merge_atoms_fail_closed(base_atoms, child_atoms, *, child_id: str):
    """Union by atom id. A child override may only RAISE severity, never lower it — and may
    never rewrite an inherited id's content, at any severity. Raising severity is not a
    licence to substitute what the atom checks for, where it is checked, or what it
    depends on."""
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
            rewritten = _rewritten_atom_fields(base_atom, atom)
            if rewritten:
                raise PromptCraftError(
                    "CONTRACT_RELAXATION",
                    f"character {child_id!r} rewrites faction atom {atom.id!r}'s "
                    f"{', '.join(rewritten)}; substituting content is not a raise",
                    hint=_RELAXATION_HINT,
                )
            # Keep inherited content; only severity may change (and only upward).
            by_id[atom.id] = base_atom.model_copy(update={"severity": atom.severity})
        else:
            by_id[atom.id] = atom

    # A character cannot silently DROP a faction-required atom: it simply isn't in child_ids,
    # so the base version survives the union above. That is the fail-closed default — inherited
    # required atoms always carry through UNCHANGED except for a severity raise.
    del child_ids  # (kept for readability of the invariant; not used)
    # Preserve base order, then append child-only atoms in declared order.
    ordered = [by_id[a.id] for a in base_atoms]
    base_ids = {b.id for b in base_atoms}
    ordered.extend(by_id[atom.id] for atom in child_atoms if atom.id not in base_ids)
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
            rewritten = _rewritten_must_not_fields(base_mn, m)
            if rewritten:
                raise PromptCraftError(
                    "CONTRACT_RELAXATION",
                    f"character {child_id!r} rewrites faction must_not {m.id!r}'s "
                    f"{', '.join(rewritten)}; substituting content is not a raise",
                    hint=_RELAXATION_HINT,
                )
            by_id[m.id] = base_mn.model_copy(update={"severity": m.severity})
        else:
            by_id[m.id] = m
    return list(by_id.values())
