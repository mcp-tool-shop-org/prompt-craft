"""Compile a resolved contract's atoms into a DSG-style dependency DAG of verifier questions.

This is the DERIVED half of "the same atom list used twice": ``synth/`` uses the atoms to build the
prompt; this module uses the same atoms to build the gate's questions. Each ``must_have`` atom -> one
``affirm`` probe; each ``must_not`` -> one ``negate`` (inverted) probe (reject if P('Yes') is high).

The DAG carries ``depends_on`` edges so the gate can evaluate parents first and mark a child N/A when
its parent fails (a NO parent forces NO on descendants) — killing the "verify the colour of an axe
that isn't there" class of false confidence."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from .schema import CheckType, ResolvedContract, Severity, Spatial


class Polarity(str, Enum):
    affirm = "affirm"  # must_have: present == good
    negate = "negate"  # must_not: present == bad (inverted probe)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str
    text: str  # the natural-language probe, e.g. "Does this show a crimson tabard?"
    check_type: CheckType
    polarity: Polarity
    severity: Severity
    depends_on: str | None = None
    spatial: Spatial | None = None
    enum: list[str] | None = None


class QuestionDAG(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: str
    questions: list[Question]

    def by_id(self, atom_id: str) -> Question | None:
        return next((q for q in self.questions if q.atom_id == atom_id), None)

    def topological(self) -> list[Question]:
        """Parents before children. Raises on a dependency cycle (fail-closed)."""
        order: list[Question] = []
        visiting: set[str] = set()
        done: set[str] = set()
        index = {q.atom_id: q for q in self.questions}

        def visit(q: Question) -> None:
            if q.atom_id in done:
                return
            if q.atom_id in visiting:
                raise ValueError(f"dependency cycle at atom {q.atom_id!r}")
            visiting.add(q.atom_id)
            if q.depends_on and q.depends_on in index:
                visit(index[q.depends_on])
            visiting.discard(q.atom_id)
            done.add(q.atom_id)
            order.append(q)

        for q in self.questions:
            visit(q)
        return order


def _affirm_text(claim: str) -> str:
    return f"Does this image show {claim}?"


def _negate_text(claim: str) -> str:
    return f"Does this image contain {claim}?"


def compile_questions(resolved: ResolvedContract) -> QuestionDAG:
    """Derive the gate's question DAG from the contract. Deterministic and order-stable."""
    questions: list[Question] = []

    for atom in resolved.must_have:
        questions.append(
            Question(
                atom_id=atom.id,
                text=_affirm_text(atom.claim),
                check_type=atom.check_type,
                polarity=Polarity.affirm,
                severity=atom.severity,
                depends_on=atom.depends_on,
                spatial=atom.spatial,
                enum=atom.enum,
            )
        )

    for mn in resolved.must_not:
        questions.append(
            Question(
                atom_id=mn.id,
                text=_negate_text(mn.claim),
                check_type=mn.check_type,
                polarity=Polarity.negate,
                # ⚑ CORRECTED IN PLACE. This read `Severity.required` with the comment "a violated
                # must_not is always blocking". That was a claim about the CONTRACT that only held
                # because the schema could not express anything else. A negation's blocking power
                # now tracks the evidence behind the check enforcing it — see MustNot.severity.
                # The schema default is still `required`, so no existing contract changed meaning.
                severity=mn.severity,
                depends_on=None,
                spatial=mn.spatial,
                enum=mn.enum,
            )
        )

    return QuestionDAG(contract_id=resolved.id, questions=questions)
