"""Where each resolved atom came from -- a read-only view over the loader's own decisions.

``ContractStore.explain(id)`` answers the question an author composing a character through
``extends`` could not previously ask: *what does this contract require after inheritance, and
which atoms came from the faction rather than being added here?* (F-ea403b5a, completing the
half of FEAT-005 that shipped without ``explain()`` / ``questions_preview()``.)

THE BOUNDARY, stated once because it is the whole design: this module REPORTS, it never
DECIDES. Every fact it prints is one ``loader.resolve()`` already established --

* the lineage comes from ``_walk_extends``;
* the final severity of every atom is read off the ``ResolvedContract``, not recomputed;
* severity ORDER is compared with the loader's own ``_severity_rank``, so "raised" here and
  "relaxation" there cannot mean two different things;
* content rewrites are not re-derived at all: ``_merge_atoms_fail_closed`` REFUSES them, so a
  contract that reaches this module has none by construction. Re-checking would be a second
  opinion about a question the loader has already closed fail-closed.

and it runs the real ``resolve()`` first, so a contract the loader would refuse is refused
here, with the same code, before a single line is reported about it.

There is deliberately NO write path (out of scope per the FEAT-005 recommendation this
completes): nothing in this module opens, writes, or renames a file.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .schema import Atom, Contract, MustNot, Severity

MUST_HAVE = "must_have"
MUST_NOT = "must_not"


class AtomOrigin(BaseModel):
    """One resolved atom, tagged with where in the lineage it came from."""

    model_config = ConfigDict(extra="forbid")
    atom_id: str
    polarity: str  # MUST_HAVE | MUST_NOT -- a negation is not a requirement
    origin: str  # the contract id that FIRST declared this atom
    inherited: bool  # origin is not the contract being explained
    severity: Severity  # as RESOLVED -- read off the ResolvedContract, not recomputed
    base_severity: Severity | None = None  # what `origin` declared, when someone restated it
    severity_raised: bool = False  # the one change a child may make to an inherited atom
    redeclared_by: list[str] = Field(default_factory=list)  # descendants that restated the id


class ContractExplain(BaseModel):
    """The lineage plus one ``AtomOrigin`` per resolved atom, must_have first."""

    model_config = ConfigDict(extra="forbid")
    contract_id: str
    lineage: list[str]
    atoms: list[AtomOrigin]

    def by_id(self, atom_id: str) -> AtomOrigin | None:
        return next((a for a in self.atoms if a.atom_id == atom_id), None)

    def inherited_ids(self) -> list[str]:
        """Ids this contract received from its base(s), in resolved order."""
        return [a.atom_id for a in self.atoms if a.inherited]

    def own_ids(self) -> list[str]:
        """Ids this contract declared itself."""
        return [a.atom_id for a in self.atoms if not a.inherited]

    def describe(self) -> list[str]:
        """One ASCII line per atom, under a lineage header. The CLI prints these verbatim.

        ASCII and unwrapped by the same doctrine as every other human surface in this
        package: no box glyphs, no colour, indentation carries the hierarchy.
        """
        lines = [f"{self.contract_id}  lineage: {' -> '.join(self.lineage)}"]
        for atom in self.atoms:
            where = f"from {atom.origin}" if atom.inherited else "declared here"
            raised = ""
            if atom.severity_raised and atom.base_severity is not None:
                raised = f", raised {atom.base_severity.value} -> {atom.severity.value}"
            lines.append(
                f"  {atom.polarity:9} {atom.atom_id}  [{atom.severity.value}] {where}{raised}"
            )
        return lines


def explain_contract(contract: Contract, lookup) -> ContractExplain:
    """Build the report. ``lookup(id) -> Contract | None``, exactly as ``loader.resolve``.

    Deferred imports: ``loader`` imports this module for its return type only (under
    ``TYPE_CHECKING``), and importing it here at module scope would close that into a cycle.
    """
    from .loader import _severity_rank, _walk_extends, resolve

    resolved = resolve(contract, lookup)  # every fail-closed check runs FIRST, unchanged
    chain = _walk_extends(contract, lookup)  # [root, ..., contract]

    origins: dict[str, tuple[str, Severity]] = {}  # atom id -> (first declarer, its severity)
    redeclared: dict[str, list[str]] = {}
    for level in chain:
        # Annotated for the same reason loader._reject_unknown_depends_on annotates its own
        # splat: the join of Atom and MustNot is BaseModel, which has neither .id nor .severity.
        declared: tuple[Atom | MustNot, ...] = (*level.must_have, *level.must_not)
        for item in declared:
            if item.id in origins:
                redeclared.setdefault(item.id, []).append(level.id)
            else:
                origins[item.id] = (level.id, item.severity)

    atoms: list[AtomOrigin] = []
    for polarity, items in ((MUST_HAVE, resolved.must_have), (MUST_NOT, resolved.must_not)):
        for item in items:
            origin, base_severity = origins[item.id]
            restated = redeclared.get(item.id, [])
            atoms.append(
                AtomOrigin(
                    atom_id=item.id,
                    polarity=polarity,
                    origin=origin,
                    inherited=origin != resolved.id,
                    severity=item.severity,
                    base_severity=base_severity if restated else None,
                    severity_raised=bool(restated)
                    and _severity_rank(item.severity) > _severity_rank(base_severity),
                    redeclared_by=list(restated),
                )
            )
    return ContractExplain(contract_id=resolved.id, lineage=list(resolved.lineage), atoms=atoms)
