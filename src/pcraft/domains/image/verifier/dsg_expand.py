"""Davidsonian Scene Graph expansion. GPU-free.

Cho et al. 2024 (arXiv:2310.18235): a claim becomes entity / attribute /
relation yes-no probes. A missing entity makes the dependents N/A.

The template decomposer is the pinned default. A caller may inject a QG
function; that is the ``qg_model`` slot. No LM runs on the per-asset path
unless the caller wired one.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ....core.contract.compile_questions import Question
from ....errors import PromptCraftError

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

    @model_validator(mode="after")
    def _reject_duplicate_probe_ids(self) -> DSGExpansion:
        """Fail closed on a repeated probe id (F-f5cc9257), the way ``ResolvedContract`` does.

        ``topological()`` keys its walk purely by id: the ``index`` dict keeps the LAST probe with a
        given id while the ``done`` set keeps the FIRST, so a duplicate silently vanished from the
        order and which declaration survived was an accident of list order. MEASURED: an expansion
        with two probes sharing id 'p1' constructed with zero error and ``topological()`` returned 1
        probe for 2 in. ``_reject_duplicate_ids`` in ``core/contract/schema.py`` refuses exactly this
        shape at construction time, for exactly this reason: a walker's dedup must never be the
        enforcement mechanism.
        """
        seen: set[str] = set()
        for probe in self.probes:
            if probe.id in seen:
                raise PromptCraftError(
                    "CONTRACT_DUPLICATE_PROBE_ID",
                    f"DSG expansion for atom {self.atom_id!r} (source {self.source!r}) declares "
                    f"probe id {probe.id!r} more than once",
                    hint="Each probe id must be unique within one expansion. A duplicate is not "
                    "deterministically evaluated -- the dependency walk keeps only one "
                    "declaration and drops the rest. If this came from an injected qg, give each "
                    "probe its own id.",
                )
            seen.add(probe.id)
        return self

    def topological(self) -> list[SubProbe]:
        """Parent-first probe order, or a coded refusal.

        F-f5cc9257: this is the image domain's own copy of the walker in
        ``core/contract/compile_questions.py``, and it never received the cycle guard that one got.
        ``QuestionDAG.topological`` carries a ``visiting`` set and raises
        ``CONTRACT_CYCLIC_DEPENDS_ON``; this added to ``done`` only AFTER the recursive call, so a
        two-probe cycle recursed forever. MEASURED: probes p1.depends_on='p2' and p2.depends_on='p1'
        raised a raw ``RecursionError`` here -- a RuntimeError, outside the PromptCraftError
        hierarchy -- while the sibling raised the coded refusal on the identical shape. Driven
        through ``DSGVerifier.score`` it was then swallowed by ``harness._safe_score``'s bare
        ``except Exception`` into a SKIPPED verdict reading 'dsg.localizer.v1 raised RecursionError',
        so a malformed expansion presented as an UNAVAILABLE INSTRUMENT.

        REACHABILITY, stated honestly: the shipped ``template_expand`` never emits a cycle (it always
        emits the entity probe every attribute/relation depends on), so this is reachable only
        through the injected ``qg`` slot -- but that slot is a documented, advertised extension
        point, and an injected QG is exactly the caller whose edges nothing else validates.
        """
        index = {p.id: p for p in self.probes}
        order: list[SubProbe] = []
        done: set[str] = set()
        visiting: list[str] = []  # a list, not a set, so the refusal can name the cycle it found

        def visit(probe: SubProbe) -> None:
            if probe.id in done:
                return
            if probe.id in visiting:
                cycle = [*visiting[visiting.index(probe.id) :], probe.id]
                raise PromptCraftError(
                    "CONTRACT_CYCLIC_DEPENDS_ON",
                    f"DSG expansion for atom {self.atom_id!r} (source {self.source!r}) has a "
                    f"depends_on cycle {' -> '.join(cycle)}, so no parent-first probe order exists",
                    hint="A DSG probe may only depend on a probe evaluated before it -- a missing "
                    "entity is what makes its dependents N/A, and a cycle has no first probe. "
                    "Break the cycle in the expansion's depends_on edges.",
                )
            visiting.append(probe.id)
            if probe.depends_on and probe.depends_on in index:
                visit(index[probe.depends_on])
            visiting.pop()
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
