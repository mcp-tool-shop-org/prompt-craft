"""Davidsonian Scene Graph expansion. GPU-free.

Cho et al. 2024 (arXiv:2310.18235): a claim becomes entity / attribute /
relation yes-no probes. A missing entity makes the dependents N/A.

The template decomposer is the pinned default. A caller may inject a QG
function; that is the ``qg_model`` slot. No LM runs on the per-asset path
unless the caller wired one.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ....core.contract.compile_questions import Question

_ARTICLES = frozenset({"a", "an", "the"})
_AFFIRM_PREFIX = "Does this image show "
_NEGATE_PREFIX = "Does this image contain "

# Longest-first so "worn over" wins over "worn".
_RELATIONS: tuple[tuple[str, str], ...] = (
    (" held in ", "held in"),
    (" worn over ", "worn over"),
    (" worn on ", "worn on"),
    (" held ", "held"),
    (" worn ", "worn"),
    (" on the ", "on the"),
)


class SubProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    kind: str  # claim | entity | attribute | relation
    depends_on: str | None = None


class DSGExpansion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str
    source: str
    probes: list[SubProbe]
    scores: dict[str, float | None] = Field(default_factory=dict)

    def topological(self) -> list[SubProbe]:
        index = {p.id: p for p in self.probes}
        order: list[SubProbe] = []
        done: set[str] = set()

        def visit(probe: SubProbe) -> None:
            if probe.id in done:
                return
            if probe.depends_on and probe.depends_on in index:
                visit(index[probe.depends_on])
            done.add(probe.id)
            order.append(probe)

        for probe in self.probes:
            visit(probe)
        return order


def claim_of(question: Question) -> str:
    text = question.text.strip()
    for prefix in (_AFFIRM_PREFIX, _NEGATE_PREFIX):
        if text.startswith(prefix) and text.endswith("?"):
            return text[len(prefix) : -1].strip()
    return text.rstrip("?").strip()


def _strip_article(phrase: str) -> str:
    words = phrase.split()
    if words and words[0].lower() in _ARTICLES:
        return " ".join(words[1:])
    return phrase


def _ask(prefix: str, body: str) -> str:
    body = body.strip().rstrip("?.")
    return f"{prefix}{body}?"


def template_expand(question: Question) -> DSGExpansion:
    """Split a contract probe into entity + attribute + relation questions."""
    claim = claim_of(question)
    prefix = _NEGATE_PREFIX if "contain " in question.text else _AFFIRM_PREFIX
    atom = question.atom_id
    entity_id = f"{atom}:entity"
    probes: list[SubProbe] = [
        SubProbe(id=f"{atom}:root", text=question.text, kind="claim", depends_on=None)
    ]

    work = claim
    relations: list[tuple[str, str]] = []
    padded = f" {work} "
    for marker, label in _RELATIONS:
        if marker in padded:
            left, right = padded.split(marker, 1)
            work = left.strip()
            tail = right.strip()
            if tail:
                relations.append((label, tail))
            padded = f" {work} "
            break

    extras: list[str] = []
    if " with " in work:
        work, rest = work.split(" with ", 1)
        extras.extend(part.strip() for part in rest.replace(",", " and ").split(" and ") if part.strip())

    bare = _strip_article(work)
    words = bare.split()
    if not words:
        return DSGExpansion(atom_id=atom, source="template.dsg.v1", probes=probes)

    head = words[-1]
    modifiers = words[:-1]
    probes.append(
        SubProbe(
            id=entity_id,
            text=_ask(prefix, f"a {head}" if head[0].islower() else head),
            kind="entity",
        )
    )
    for i, mod in enumerate(modifiers):
        probes.append(
            SubProbe(
                id=f"{atom}:attr:{i}",
                text=_ask(prefix, f"a {mod} {head}"),
                kind="attribute",
                depends_on=entity_id,
            )
        )
    for i, extra in enumerate(extras):
        probes.append(
            SubProbe(
                id=f"{atom}:with:{i}",
                text=_ask(prefix, f"a {head} with {extra}"),
                kind="attribute",
                depends_on=entity_id,
            )
        )
    for i, (label, tail) in enumerate(relations):
        probes.append(
            SubProbe(
                id=f"{atom}:rel:{i}",
                text=_ask(prefix, f"a {head} {label} {tail}"),
                kind="relation",
                depends_on=entity_id,
            )
        )
    return DSGExpansion(atom_id=atom, source="template.dsg.v1", probes=probes)
