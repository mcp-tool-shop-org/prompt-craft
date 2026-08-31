"""Contract loader: resolves ``extends`` (faction -> character), FAIL-CLOSED.

The single load-bearing rule (from sdlab identity inheritance): a character may **raise** a
severity or add atoms, but may **never drop a faction-required atom, relax its severity, or
rewrite its content (claim, check_type, spatial, enum, depends_on)** while keeping its id. The loader throws
``PromptCraftError(CONTRACT_RELAXATION)`` if it tries. One edit to a faction contract then
propagates to every member's gate automatically."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from ...errors import PromptCraftError
from .schema import SUPPORTED_CONTRACT_SCHEMAS, Contract, IdentityRef, ResolvedContract, Severity


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
    declared = data.get("$schema") if isinstance(data, dict) else None
    if declared is not None and declared not in SUPPORTED_CONTRACT_SCHEMAS:
        raise PromptCraftError(
            "CONTRACT_SCHEMA_UNSUPPORTED",
            f"contract {path} declares $schema {declared!r}; this build reads "
            f"{sorted(SUPPORTED_CONTRACT_SCHEMAS)}",
        )
    try:
        return Contract.model_validate(data)
    except PromptCraftError:
        # A guard inside a @model_validator (duplicate atom ids) already speaks the
        # structured shape and carries a precise code. Pydantic does not wrap these --
        # only ValueError/TypeError/AssertionError -- so pass it through untouched.
        raise
    except ValidationError as err:
        # THE THIRD failure mode of reading a contract, closed last. The read and the
        # JSON parse above were already structured; the schema validation was not, so a
        # misspelled key, a bad enum value, or a wrong field type left this function as a
        # raw pydantic_core.ValidationError. Nothing between here and the CLI's
        # `except Exception` backstop catches that, so an ordinary authoring typo exited
        # 2 with RUNTIME_UNEXPECTED -- whose own hint calls it "the backstop, not a
        # diagnosis" -- where errors.py's namespace table and STABILITY.md's covered
        # exit-code contract both promise 1 with a CONTRACT_ code.
        raise PromptCraftError(
            "CONTRACT_INVALID",
            f"contract {path} does not match the contract schema: "
            f"{describe_validation_error(err)}",
            hint=(
                "Fix the field(s) the message names, or run `pcraft schema` to dump the "
                "authoring JSON Schema. Re-run with --debug for pydantic's full report."
            ),
            cause=err,
        ) from err


# How many field-level locations the default (non-debug) message names before it stops.
# A diagnosis, not a dump: --debug still carries every one of them, via `cause`.
_MAX_REPORTED_ERRORS = 3

# The between-entry delimiter, and the per-entry ordinal that survives a message which
# contains the delimiter anyway (F-eaa870d6). See describe_validation_error's docstring.
_ENTRY_SEP = " | "


def describe_validation_error(
    err: ValidationError, *, max_reported: int = _MAX_REPORTED_ERRORS
) -> str:
    """Summarize a pydantic ValidationError for the DEFAULT error surface (F-40a4956f).

    The refusal used to read "contract <path> does not match the contract schema" and nothing
    else -- no field name, no count, no location -- so --debug was required for ANY diagnostic
    content at all, even to learn how many things were wrong. That made CONTRACT_INVALID the
    one refusal in this file that says nothing: every sibling (CONTRACT_RELAXATION,
    CONTRACT_MISSING_BASE, CONTRACT_DUPLICATE_ATOM_ID, CONTRACT_UNKNOWN_DEPENDS_ON,
    CONTRACT_CYCLIC_DEPENDS_ON) embeds the specific id, field and values with no flag needed --
    and it is the code an ordinary authoring typo lands on, which is the most common one.

    MEASURED: pydantic was never the limit. A contract with two independently-invalid fields
    returns BOTH from ``err.errors()``, and --debug already printed pydantic's own
    "2 validation errors for Contract" block naming both. The default path was discarding it.
    So this reports the COUNT plus every location, not just the first -- capped, because a
    console line is not a report, and the full list stays one --debug away.

    Only ``loc`` and ``msg`` are used. The offending ``input`` value is deliberately left out:
    it is arbitrary text from a file we did not write, and this string is printed to a console
    whose codepage we do not control (F-fd21bd37).

    [!] THE DELIMITER IS NOT "; " (F-eaa870d6). The aggregate joined entries with "; " and
    prefixed the count with "; " too -- while two of this schema's own field validators
    (``_reject_blank_id``, ``_reject_blank_claim``) raise ValueError text that CONTAINS "; ":
    "id must not be blank; '   ' is empty once stripped". Pydantic folds that into the
    per-field ``msg``, so the same two characters played three roles in one run-on line and a
    reader could not tell where one field's clause ended and the next entry began without
    already knowing the "field.path:" pattern to look for. The authoring mistake that produces
    it is ordinary: copy a template atom, forget to fill in both its id and its claim.

    Two mechanisms, because one is not enough. ``_ENTRY_SEP`` separates entries, and each entry
    is numbered ``[n]``. The separator does the reading; the ordinals are what still segment the
    line if a message ever contains the separator itself -- ``msg`` can embed a ``repr`` of
    author-written text, so no single character is safe to assume absent. The count and the
    "(+n more)" pointer are chunks of the same sequence, not exceptions to it.

    Shared with ``optimize/artifact.load_pinned`` (F-936b313e), which had the same
    says-nothing-by-default refusal for the same on-disk-JSON-vs-pydantic-model failure. It is
    one function rather than two copies so the next improvement here cannot fail to reach that
    sibling -- which is exactly how that finding was born. Its natural home is ``pcraft.errors``
    beside ``PromptCraftError``; it lives here because this is where its history is.
    """
    errors = err.errors()
    shown = errors[:max_reported]
    parts = [
        f"[{n}] {'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
        for n, e in enumerate(shown, start=1)
    ]
    remaining = len(errors) - len(shown)
    if remaining > 0:
        parts.append(f"(+{remaining} more, see --debug)")
    return _ENTRY_SEP.join([f"{len(errors)} error(s)", *parts])


_MAX_EXTENDS_DEPTH = 64
"""How many ``extends`` hops one walk may take before it is refused (F-ca6f8509).

Not the cycle guard -- the visited set below is. This is the backstop for a ``lookup`` that
MANUFACTURES contracts rather than reading a finite store: a real ``ContractStore`` bounds any
chain by its own id count, but ``lookup`` is an arbitrary callable (``optimize/compile.py``
assembles contracts programmatically), and an unbounded walk with no repeat to detect would
spin instead of refusing. 64 is far past any authored inheritance depth -- the shipped example
is 2 -- so it can only be reached by that pathological shape."""


def resolve(contract: Contract, lookup) -> ResolvedContract:
    """Merge a contract with its faction base. ``lookup(id) -> Contract | None``.

    A faction resolves to itself. A character merges its faction base then its own atoms,
    enforcing the no-relaxation rule. Multi-level chains (character extends character extends
    faction) are supported; CYCLIC ones are refused -- see ``_walk_extends``.

    [!] ITERATIVE, not recursive (F-ca6f8509). This function used to call itself on
    ``contract.extends``, which made a self-extending contract -- a one-line typo,
    ``"extends": "<its own id>"``, indistinguishable from copy-pasting a template contract and
    forgetting to retarget it -- die as a raw ``RecursionError``: an exception from outside
    the ``PromptCraftError`` hierarchy crossing this module's documented boundary, reported by
    the CLI backstop as RUNTIME_UNEXPECTED (exit 2, "prompt-craft crashed") for what is
    exit-1 user input. That is the same defect class already closed three times in this
    package (F-45c39f7d, F-84788251, F-2b317b56), landing a fourth time on the sibling
    mechanism the ``depends_on`` cycle fix never touched.

    Detecting the cycle would have been enough to stop the typo; walking iteratively is what
    makes ``RecursionError`` IMPOSSIBLE on this path rather than merely unlikely, because a
    long-enough LEGITIMATE chain would otherwise exhaust the stack by the same road. The walk
    now costs one Python frame regardless of chain length.
    """
    chain = _walk_extends(contract, lookup)  # [root, ..., contract]; root first
    # depends_on referential integrity + acyclicity are enforced by ResolvedContract's own
    # @model_validator (schema.py), so they hold for EVERY construction path rather than
    # only this one. See _reject_unknown_depends_on's F-877a8d9b note for what moved and why.
    root = chain[0]
    resolved = ResolvedContract(
        id=root.id,
        level=root.level,
        lineage=[root.id],
        must_have=list(root.must_have),
        must_not=list(root.must_not),
        identity_refs=[root.identity_ref] if root.identity_ref else [],
    )
    for child in chain[1:]:
        merged_must_have = _merge_atoms_fail_closed(
            resolved.must_have, child.must_have, child_id=child.id
        )
        merged_must_not = _merge_must_not(resolved.must_not, child.must_not, child_id=child.id)
        identity_refs = _merge_identity_refs(
            resolved.identity_refs, child.identity_ref, child_id=child.id
        )
        # The depends_on checks run POST-merge -- a character legitimately depends on an atom it
        # inherits rather than declares, so checking the raw child would refuse valid contracts.
        # They run inside ResolvedContract's validator below, which IS post-merge by
        # construction, so the merged lists are still what gets checked -- once per level, exactly
        # as the recursive form checked every intermediate resolution.
        resolved = ResolvedContract(
            id=child.id,
            level=child.level,
            lineage=[*resolved.lineage, child.id],
            must_have=merged_must_have,
            must_not=merged_must_not,
            identity_refs=identity_refs,
        )
    return resolved


def _walk_extends(contract: Contract, lookup) -> list[Contract]:
    """Follow ``extends`` up to the base, ROOT FIRST. Refuses a cycle; never recurses.

    A ``faction``, and any contract with no ``extends``, terminates the walk -- so the walk
    stops exactly where the old base case returned. Mirrors ``schema._reject_cyclic_depends_on``:
    each contract has at most one parent, so the graph is functional and a plain chain-walk
    from the starting node finds any cycle it can reach, with the first repeated id
    necessarily ON the cycle.
    """
    chain: list[Contract] = [contract]
    seen: set[str] = {contract.id}
    current = contract
    while current.level != "faction" and current.extends is not None:
        if current.extends in seen:
            ids = [c.id for c in chain]
            if current.extends in ids:
                cycle = ids[ids.index(current.extends) :]
                path = " -> ".join([*cycle, cycle[0]])
            else:
                # Defensive, and deliberately not an `index()` away from a crash: `lookup` is
                # an arbitrary callable, so one that returns a contract whose id differs from
                # the key it was ASKED for can leave a key in `seen` that never entered the
                # chain. Trace what was actually walked rather than raising a bare ValueError
                # out of the refusal itself -- which would be this finding's own defect class,
                # committed inside its fix.
                path = " -> ".join([*ids, current.extends])
            raise PromptCraftError(
                "CONTRACT_CYCLIC_EXTENDS",
                f"{contract.id!r} has an extends cycle: {path}",
                hint=(
                    "extends is an inheritance edge: a contract's base is resolved first so "
                    "the child can add to it. A cycle has no base, so there is nothing to "
                    "inherit from. Point extends at the faction this contract belongs to -- "
                    "a contract may not extend itself, directly or through its ancestors."
                ),
            )
        base_contract = lookup(current.extends)
        if base_contract is None:
            raise PromptCraftError(
                "CONTRACT_MISSING_BASE",
                f"{current.id!r} extends {current.extends!r} but that faction is not in the store",
            )
        seen.add(current.extends)
        seen.add(base_contract.id)
        chain.append(base_contract)
        current = base_contract
        if len(chain) > _MAX_EXTENDS_DEPTH:
            raise PromptCraftError(
                "CONTRACT_EXTENDS_TOO_DEEP",
                f"{contract.id!r} extends through more than {_MAX_EXTENDS_DEPTH} contracts",
                hint=(
                    "An inheritance chain this long is not an authored contract tree. Point "
                    "the character at the faction it belongs to. This ceiling exists so a "
                    "lookup that generates contracts on demand refuses instead of walking "
                    "forever."
                ),
            )
    chain.reverse()
    return chain


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


# Blocking power, ascending. Written out rather than derived from the enum: `Severity`
# declares `required` FIRST, so `{s: i for i, s in enumerate(Severity)}` would rank
# required below optional and silently invert every comparison below -- turning the
# fail-closed relaxation guard into a pass-open one. Declaration order is not severity
# order, and no future reordering of the enum may be allowed to imply that it is.
#
# What this table must not do is fall through. `_SEVERITY_RANK[atom.severity]` was a bare
# subscript, so the day a third member joins `Severity` every merge touching it raises a
# raw KeyError out of the loader -- an exception from outside the PromptCraftError
# hierarchy crossing the boundary this module documents, exactly like the pydantic
# ValidationError closed in `_read_contract`. `_severity_rank` is the only sanctioned
# reader; `test_the_severity_rank_table_covers_every_severity_member` goes red the day a
# member is added without a rank, which is the intended place to find out.
_SEVERITY_RANK = {Severity.optional: 0, Severity.required: 1}


def _severity_rank(severity) -> int:
    """Rank a severity, or refuse in the documented shape. Never KeyError."""
    rank = _SEVERITY_RANK.get(severity)
    if rank is None:
        raise PromptCraftError(
            "CONTRACT_UNKNOWN_SEVERITY",
            f"this build cannot rank severity {severity!r}",
            hint=(
                "A severity was added to the Severity enum without a blocking-power rank. "
                "Add it to _SEVERITY_RANK in core/contract/loader.py, ordered by how much "
                "it blocks -- the loader refuses rather than guess whether it relaxes an "
                "inherited requirement."
            ),
        )
    return rank


# The depends_on referential check that used to live here (F-19f97de2) now lives on
# ResolvedContract itself as part of _check_depends_on_edges, alongside the cycle check added
# with it (schema._reject_unknown_depends_on / _reject_cyclic_depends_on). It was moved
# because an imperative call inside resolve() makes an invariant a property of one code path;
# a @model_validator makes it a property of the type. Nothing in this module calls it now --
# each ResolvedContract(...) construction in resolve() above IS the check.


_RELAXATION_HINT = (
    "A character contract may not drop or relax a faction-required atom, and may not "
    "rewrite an inherited atom's claim, check_type, spatial, enum, or depends_on, "
    "or neutralize an inherited identity plate. Raise the severity or weight, or add "
    "a new id or plate -- never substitute an existing id's content."
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
    """Union by atom id. A child override may only RAISE severity, never lower it -- and may
    never rewrite an inherited id's content, at any severity. Raising severity is not a
    licence to substitute what the atom checks for, where it is checked, or what it
    depends on."""
    by_id = {a.id: a for a in base_atoms}
    child_ids = {a.id for a in child_atoms}

    for atom in child_atoms:
        base_atom = by_id.get(atom.id)
        if base_atom is not None:
            if _severity_rank(atom.severity) < _severity_rank(base_atom.severity):
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
    # so the base version survives the union above. That is the fail-closed default -- inherited
    # required atoms always carry through UNCHANGED except for a severity raise.
    del child_ids  # (kept for readability of the invariant; not used)
    # Preserve base order, then append child-only atoms in declared order.
    ordered = [by_id[a.id] for a in base_atoms]
    base_ids = {b.id for b in base_atoms}
    ordered.extend(by_id[atom.id] for atom in child_atoms if atom.id not in base_ids)
    return ordered


def _merge_must_not(base, child, *, child_id: str):
    """Union by id, fail-closed on severity -- the same rule ``_merge_atoms_fail_closed`` enforces.

    [!] This guard was ADDED when ``MustNot`` gained a severity, and it closes a hole that change
    opened. Before the field existed every negation was required by construction, so a plain
    override could not relax anything and none was needed. The moment a negation can be
    ``optional``, a character contract could override an inherited ``required`` negation down to
    ``optional`` and the loader would allow it -- silently relaxing the exact kind of inherited
    requirement this module exists to protect.

    Measured before the fix: a faction declaring ``no_gun`` required and a character re-declaring
    it optional resolved to optional, no error.

    [!] SECOND GUARD, same finding (F-a5fa3f8b). Severity-lowering was the *loud* attack; a child
    could still keep ``no_gun``'s id and severity while rewriting its claim from "a firearm" to
    "a rubber duck" -- same blocking power, different (or no) actual constraint. Claim/check_type
    are now frozen on a redeclared id, exactly as for ``must_have`` in ``_merge_atoms_fail_closed``.
    """
    by_id = {m.id: m for m in base}
    for m in child:
        base_mn = by_id.get(m.id)
        if base_mn is not None:
            if _severity_rank(m.severity) < _severity_rank(base_mn.severity):
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
