"""The Contract: a typed spec of atomic *depictable* claims -- NOT a prose prompt.

This replaces the opaque ``{name, prompt, weapon_class}`` triple that prompt-craft supersedes,
and it is a typed pydantic transcription of style-dataset-lab's identity-gates spec
(non_negotiable_details -> must_have, forbidden_drift_cues -> must_not, reference plate ->
identity_ref). Prose prompts are a *derived, regenerable* artifact (see ``synth/``); they never
live in the contract.

Two levels with inheritance: a ``faction`` is the base class; a ``character`` ``extends`` a faction
and may ADD or RAISE requirements but may never drop or relax a faction-required atom, nor rewrite
its content (claim, check_type, spatial, enum, depends_on) while keeping its id
(enforced fail-closed in ``loader.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...errors import PromptCraftError


class CheckType(StrEnum):
    """Selects which gate tier verifies an atom (cheapest first)."""

    siglip2 = "siglip2"  # Tier-0: cheap closed-set / presence screen (sigmoid, per-query)
    vqa = "vqa"  # Tier-1: compositional VQAScore P('Yes')
    palette = "palette"  # deterministic colour check (no model)


class Severity(StrEnum):
    required = "required"  # a required atom blocks bind on failure (andon)
    optional = "optional"  # an optional atom only warns


class SpatialKind(StrEnum):
    region = "region"  # a named image region (torso, head, hands, chest-center)
    pose = "pose"  # a ControlNet pose/openpose reference image that locks geometry


class Spatial(BaseModel):
    """Where an atom must hold. ``region`` -> a checkable image region; ``pose`` -> a ControlNet ref
    that the generator uses to *lock* geometry (text cannot place 'axe in right hand'; the guide can)."""

    model_config = ConfigDict(extra="forbid")
    kind: SpatialKind
    ref: str  # region name, or a path to an openpose/controlnet image for kind=pose


_NON_EMPTY_ID_RATIONALE = """Why every id carries min_length=1 (F-bd78997e).

``Atom.id``, ``MustNot.id`` and ``Contract.id`` accepted the empty string, and
``Atom(id='', claim='x', check_type=CheckType.vqa)`` constructed without complaint. That is
the one input class that separates ``compile_questions.py``'s dependency guard
``if q.depends_on and q.depends_on in index`` from the mutant that drops the first arm: with
an empty id in the DAG index, ``'' in index`` becomes True, and an atom whose ``depends_on``
is the empty string acquires a parent edge the original never gave it. The divergence is a
benign visit reordering rather than a crash, so the mutant was classified equivalent -- but
the classification rested on ids never being empty, which nothing enforced.

An empty id is not a contract anyone means to write. Refusing it at construction closes the
input class, so the equivalence argument holds on a schema guarantee instead of an
assumption -- the same shape as rejecting duplicate ids here rather than letting the DAG's
own dedup be the enforcement mechanism."""

_BLANK_ID_RATIONALE = """Why the floor above is measured AFTER stripping (F-7409e175).

``Field(min_length=1)`` counts raw Python characters, so it closes the empty string and
nothing else. MEASURED: ``Atom(id='   ')`` satisfies the floor with a length of 3 and
constructs untouched, as do ``MustNot(id=' ')`` and ``Atom(id='\\t\\n')``. That is the letter
of the floor rather than the rationale above it -- "an empty id is not a contract anyone
means to write" applies with the same force to an id that LOOKS empty everywhere it is ever
shown: in the compiled DAG, in a receipt, and inside the refusal messages that quote the id
back to the author.

The gap is narrow and no downstream defect was found. It does not reopen the CQ58 drop-first
mutant (Python string falsiness is False only for the empty string, so a whitespace-only id
is truthy and the short-circuit behaves exactly as the original), and it does not defeat
CONTRACT_DUPLICATE_ATOM_ID (exact string equality is used everywhere an id is compared, so
``' tabard'`` and ``'tabard'`` are consistently two distinct nodes rather than a silent
collision). What is left is a typo class: a stray copy-pasted space in hand-authored contract
JSON, which should fail closed at construction like every other malformed id rather than name
a node no reader can identify.

Only BLANK is refused. An id carrying incidental leading, inner, or trailing whitespace is
stored exactly as authored -- NORMALIZING it would silently merge ids that the DAG index, the
duplicate guard, and every dict key in this domain currently treat as distinct, which is a
much larger behaviour change than this gap justifies."""


_BLANK_CLAIM_RATIONALE = """Why ``claim`` carries the same non-blank floor as ``id`` (F-588763b4).

``Atom.claim`` and ``MustNot.claim`` were bare ``claim: str`` while ``id`` on the same two
classes carried ``Field(min_length=1)`` PLUS ``_reject_blank_id`` -- and the two rationales
above spend their length arguing that a blank id "is not a contract anyone means to write" and
must be refused at construction rather than trusted to a downstream consumer. The identical
argument applies with at least equal force to ``claim``: it is the field ``Atom``'s own
docstring calls "a single visible claim, phrased as a checkable statement", i.e. the entire
content of the atom.

MEASURED before this guard: ``Atom(id='a1', claim='')`` and ``Atom(id='a2', claim='   ')``
both constructed cleanly; ``TemplateSynthesizer.synthesize()`` then produced a prompt with a
bare leading comma (the empty token contributes nothing between joins), and
``compile_questions`` emitted ``Question.text="Does this image show ?"`` for the affirm probe
-- a REQUIRED-severity question with no content, sent to whatever verifier tier handles it.

``assert_tokens_trace`` does not flag this and does not need to: an empty normalized segment is
correctly skipped by its own job. The one existing backstop is ``synth/assert_.py``'s
``assert_coverage``, which WOULD catch it (an empty claim means an empty coverage phrase, so
the required atom lands in ``missing`` -> SYNTH_COVERAGE_MISSING) -- but only for callers that
remember to invoke it. That is the same "not the only way to obtain a ResolvedContract" gap
F-877a8d9b named for ``depends_on`` before that check moved onto the type. On the type, the
invariant holds for every construction path.

Only BLANK is refused, exactly as for ``id``: a claim carrying incidental leading or trailing
whitespace is stored as authored. Normalizing it would silently rewrite contract text that the
prompt, the coverage map, and the compiled question all quote verbatim."""


def _reject_blank_claim(value: str) -> str:
    """Refuse a claim that is empty once stripped. See ``_BLANK_CLAIM_RATIONALE``.

    Raises ``ValueError`` for the same reason ``_reject_blank_id`` does: pydantic folds it into
    the ValidationError that ``loader._read_contract`` already turns into CONTRACT_INVALID
    (exit 1) for an on-disk file.
    """
    if not value.strip():
        raise ValueError(f"claim must not be blank; {value!r} is empty once stripped")
    return value


def _reject_blank_id(value: str) -> str:
    """Refuse an id that is empty once stripped. See ``_BLANK_ID_RATIONALE``.

    Raises ``ValueError`` rather than ``PromptCraftError`` on purpose: pydantic folds a
    ValueError raised in a field validator into the same ``ValidationError`` that
    ``min_length=1`` already produces for the empty string, so both halves of one rule refuse
    in one shape -- and ``loader._read_contract`` turns that into CONTRACT_INVALID (exit 1)
    for an on-disk file, exactly as it already does for every other schema violation.
    """
    if not value.strip():
        raise ValueError(f"id must not be blank; {value!r} is empty once stripped")
    return value


class Atom(BaseModel):
    """One atomic depictable claim. The same atom list is used twice -- to synthesize and to gate."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)  # see _NON_EMPTY_ID_RATIONALE + _BLANK_ID_RATIONALE
    # a single visible claim, phrased as a checkable statement. See _BLANK_CLAIM_RATIONALE.
    claim: str = Field(min_length=1)
    check_type: CheckType
    severity: Severity = Severity.required
    depends_on: str | None = None  # DAG edge: this atom is only meaningful if the parent passes
    spatial: Spatial | None = None
    enum: list[str] | None = None  # closed set for siglip2/palette atoms

    @field_validator("id")
    @classmethod
    def _id_is_not_blank(cls, value: str) -> str:
        return _reject_blank_id(value)

    @field_validator("claim")
    @classmethod
    def _claim_is_not_blank(cls, value: str) -> str:
        return _reject_blank_claim(value)


class MustNot(BaseModel):
    """An anti-constraint, GATE-ENFORCED on the pixels (inverted probe) -- NOT a negative prompt.

    Negative prompts / concept-erasure leave residual features and fall to paraphrase; satisfaction
    requires the gate to confirm *absence* on the actual pixels.

    ``severity`` exists because **a negation's blocking power should match the evidence behind the
    check that enforces it.** Confirming a thing is *absent* is a different capability from
    confirming a thing is present, and it is the less established of the two: CLIP-family encoders
    are documented as limited at negation (TNG-CLIP, arXiv:2505.18434, citation-gated `supported`),
    and no located source benchmarks a sigmoid zero-shot score as an absence verifier at all.

    A negation whose verifier is calibrated for absence earns ``required`` and blocks a bind. One
    whose verifier is not yet measured on absence is ``optional``: it still runs, still scores, and
    still rides the transcript -- it simply does not assert more certainty than its evidence
    supports. This is the same principle as ``Zone.UNAVAILABLE`` and the could-not-run exit code:
    the system's claims track what it actually established.

    The default stays ``required``, so a contract written before this field means what it always
    meant. Promotion is the intended direction -- measure the verifier on absence, then raise the
    severity with the measurement in hand."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)  # see _NON_EMPTY_ID_RATIONALE + _BLANK_ID_RATIONALE
    claim: str = Field(min_length=1)  # see _BLANK_CLAIM_RATIONALE
    check_type: CheckType = CheckType.vqa
    severity: Severity = Severity.required
    spatial: Spatial | None = None
    enum: list[str] | None = None

    @field_validator("id")
    @classmethod
    def _id_is_not_blank(cls, value: str) -> str:
        return _reject_blank_id(value)

    @field_validator("claim")
    @classmethod
    def _claim_is_not_blank(cls, value: str) -> str:
        return _reject_blank_claim(value)


class IdentityRef(BaseModel):
    """Identity = CONDITIONING, never tokens. A reference plate bound by LoRA / IP-Adapter.

    The proven-correct path: anatomical tokens make diffusion render specimens; a reference image
    binds the exact face/insignia, and the gate then verifies it rendered."""

    model_config = ConfigDict(extra="forbid")
    plate: str  # path to the reference plate image (the conditioning input)
    method: str = "ip_adapter"  # ip_adapter | reference | instantid | lora | none
    weight: float = 0.6
    scope: str = "face"  # face | costume | silhouette | full


def _reject_duplicate_ids(
    must_have: Sequence[Atom], must_not: Sequence[MustNot], *, contract_id: str
) -> None:
    """Fail closed on a repeated atom id within one list (F-fb7194d3).

    ``QuestionDAG.topological()`` (``compile_questions.py``) keys its dependency walk purely
    by ``atom_id``: its ``index`` dict comprehension keeps the LAST atom with a given id, but
    its ``done`` set keeps the FIRST -- so a duplicate id silently vanishes from the compiled
    gate order with no error, and which declaration survives is an accident of list order.
    Rejecting the duplicate here, at contract-construction time, is the fail-closed default;
    the DAG's own dedup must never be the enforcement mechanism.

    The same id in ``must_have`` and ``must_not`` is also a collision: the DAG has one
    key per id, so one polarity silently disappears.
    """
    _reject_duplicates_in(must_have, contract_id=contract_id, list_name="must_have")
    _reject_duplicates_in(must_not, contract_id=contract_id, list_name="must_not")
    have_ids = {a.id for a in must_have}
    for mn in must_not:
        if mn.id in have_ids:
            raise PromptCraftError(
                "CONTRACT_DUPLICATE_ATOM_ID",
                f"{contract_id!r} uses id {mn.id!r} in both must_have and must_not",
                hint=(
                    "must_have and must_not share one id namespace. The question DAG "
                    "keys by atom_id; a shared id drops one polarity. Give the negation "
                    "its own id."
                ),
            )


def _reject_duplicates_in(
    atoms: Sequence[Atom] | Sequence[MustNot], *, contract_id: str, list_name: str
) -> None:
    seen: set[str] = set()
    for atom in atoms:
        if atom.id in seen:
            raise PromptCraftError(
                "CONTRACT_DUPLICATE_ATOM_ID",
                f"{contract_id!r} declares {list_name} id {atom.id!r} more than once",
                hint=(
                    "Each id must be unique across must_have and must_not inside one "
                    "contract. A duplicate is not deterministically evaluated -- "
                    "QuestionDAG.topological() silently keeps only one declaration "
                    "and drops the rest."
                ),
            )
        seen.add(atom.id)


def _reject_unknown_depends_on(
    must_have: Sequence[Atom], must_not: Sequence[MustNot], *, contract_id: str
) -> None:
    """Fail closed on a ``depends_on`` that names no atom in this contract (F-19f97de2).

    A typo'd parent did not fail -- it silently DEMOTED its atom to a root:
    ``QuestionDAG.topological()``'s ``if q.depends_on and q.depends_on in index`` skips the
    unknown edge, so the atom is evaluated unconditionally and the "a NO parent forces NO on
    descendants" guarantee -- the entire reason ``depends_on`` exists -- quietly does not
    apply to it. The gate then verifies the colour of an axe that is not there, which is the
    exact false confidence the DAG was built to kill.

    [!] MOVED HERE FROM ``loader.resolve()`` (F-877a8d9b). It shipped as an imperative call
    inside ``resolve()``, which made the invariant a property of ONE construction path
    instead of a property of the type. MEASURED before the move: a ``ResolvedContract`` built
    directly with ``depends_on='ghost'`` constructed with zero error, while the identical
    direct-construction style with a duplicate id raised CONTRACT_DUPLICATE_ATOM_ID
    immediately -- because THAT guard was a ``@model_validator``. The live blast radius was
    zero (every production caller reaches the DAG through ``harness.evaluate``, whose own
    ``verdicts.get(parent) is None -> SKIPPED`` arm is the other half of F-19f97de2), but
    ``loader.resolve`` is not the only way to obtain a ``ResolvedContract``: ``optimize/
    compile.py``'s GateMetric takes ``list[ResolvedContract]``, so a programmatically
    assembled GEPA trainset is a concrete caller that never touches ``ContractStore``. On the
    type, the invariant holds for every construction path.

    Runs on RESOLVED lists, never on a raw child contract: a character legitimately depends on
    an atom it INHERITS rather than declares, so a pre-merge check would refuse correct
    contracts. The id namespace spans must_have AND must_not because ``compile_questions``
    indexes both into one DAG keyed by ``atom_id`` -- the check mirrors the index the walk
    actually uses.
    """
    known = {a.id for a in must_have} | {m.id for m in must_not}
    items: tuple[Atom | MustNot, ...] = (*must_have, *must_not)
    for item in items:
        parent = getattr(item, "depends_on", None)
        if parent is None:
            continue
        if parent not in known:
            raise PromptCraftError(
                "CONTRACT_UNKNOWN_DEPENDS_ON",
                f"{contract_id!r} atom {item.id!r} depends_on {parent!r}, "
                f"which is not an atom of this contract",
                hint=(
                    "depends_on must name an id declared in this contract's must_have or "
                    "must_not (inherited atoms count, after extends is resolved). An "
                    "unresolvable parent is not 'no parent' -- the atom would be gated "
                    "unconditionally instead of only when its parent passes."
                ),
            )


def _reject_cyclic_depends_on(
    must_have: Sequence[Atom], must_not: Sequence[MustNot], *, contract_id: str
) -> None:
    """Fail closed on a ``depends_on`` cycle, at load time (F-2b317b56).

    The referential check above closed the DANGLING edge; a cycle is the other way a
    dependency graph can be unusable, and it was not refused anywhere an author would meet
    it. MEASURED before this guard: a contract whose atoms depend on each other in a 2-cycle
    passed ``pcraft validate`` with ``ok`` and exit 0 -- because ``validate`` compiles the
    DAG but never walks it -- and then died in ``bind``/``gate`` with a bare ``ValueError``
    out of ``QuestionDAG.topological()``. A self-edge (``depends_on`` naming the atom's own
    id) behaved the same way: it satisfies the referential check, since the id is present.

    Two things were wrong with that and both are fixed. The refusal now happens where the
    defect is -- the contract, not the gate run -- so ``validate`` is the command that tells
    you; and it carries a named CONTRACT_ code (exit 1, "fix your input") rather than an
    unclassified ValueError that the CLI backstop would have reported as RUNTIME_UNEXPECTED
    (exit 2, "prompt-craft crashed"). ``topological()`` keeps a cycle guard of its own, now
    raising this same code: a gate raises named codes, never bare errors.

    Each atom has at most one parent, so the graph is functional and a plain chain-walk from
    every edge-carrying node finds every cycle: the first node revisited on a walk is
    necessarily ON the cycle, because the walk from it is deterministic and returned to it.
    """
    parent_of: dict[str, str] = {}
    items: tuple[Atom | MustNot, ...] = (*must_have, *must_not)
    for item in items:
        parent = getattr(item, "depends_on", None)
        if parent is not None:
            parent_of[item.id] = parent

    settled: set[str] = set()  # ids already proven to reach a root without looping
    for start in parent_of:
        chain: list[str] = []
        seen: set[str] = set()
        node = start
        while node in parent_of and node not in seen and node not in settled:
            seen.add(node)
            chain.append(node)
            node = parent_of[node]
        if node in seen:
            cycle = chain[chain.index(node) :]
            path = " -> ".join([*cycle, cycle[0]])
            raise PromptCraftError(
                "CONTRACT_CYCLIC_DEPENDS_ON",
                f"{contract_id!r} has a depends_on cycle: {path}",
                hint=(
                    "depends_on is a DAG edge: the parent is evaluated first so a failing "
                    "parent can force NO on its descendants. A cycle has no first atom, so "
                    "there is no order the gate could run it in. Break the loop -- an atom "
                    "may not depend on itself, directly or through its ancestors."
                ),
            )
        settled |= seen


CONTRACT_SCHEMA_ID = "prompt-craft/contract.v1"
"""The on-disk contract format this build reads.

Checked in ``loader._read_contract``. It was a decorative label until v1.0.0 --
``prompt-craft/contract.v99-NONSENSE`` loaded without complaint, so a file could announce a
format nobody supports and be parsed as though it had announced nothing. A version marker that
is never compared is worse than no marker: it reads as a compatibility check to everyone who
sees it in the file."""

SUPPORTED_CONTRACT_SCHEMAS = frozenset({CONTRACT_SCHEMA_ID})


class Contract(BaseModel):
    """A single faction or character contract (unresolved -- ``extends`` not yet applied)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    schema_id: str = Field(default=CONTRACT_SCHEMA_ID, alias="$schema")
    id: str = Field(min_length=1)  # see _NON_EMPTY_ID_RATIONALE + _BLANK_ID_RATIONALE
    level: str  # "faction" | "character"
    extends: str | None = None  # a faction id, for level == "character"
    must_have: list[Atom] = Field(default_factory=list)
    must_not: list[MustNot] = Field(default_factory=list)
    identity_ref: IdentityRef | None = None
    # A narrowly-declared allow-list entry, not a reopening of extra="ignore": both shipped
    # example contracts (src/pcraft/domains/image/subdomains/sprite/contracts/) carry a
    # top-level "_note" authoring comment. Declaring it explicitly keeps that field legal
    # while every OTHER unknown/misspelled key (musthave, mustnot, extend, ...) still fails
    # closed instead of being silently dropped along with it.
    note: str | None = Field(default=None, alias="_note")

    @field_validator("id")
    @classmethod
    def _id_is_not_blank(cls, value: str) -> str:
        return _reject_blank_id(value)

    @model_validator(mode="after")
    def _check_unique_atom_ids(self) -> Contract:
        _reject_duplicate_ids(self.must_have, self.must_not, contract_id=self.id)
        return self


def export_json_schema() -> dict:
    """JSON Schema for the authoring contract. The CLI dumps this."""
    return Contract.model_json_schema()


class ResolvedContract(BaseModel):
    """A character contract with its faction base merged in (output of ``loader.resolve``).

    ``identity_refs`` is a LIST: the faction costume plate composes with the character face plate."""

    model_config = ConfigDict(extra="forbid")
    id: str
    level: str
    lineage: list[str]  # [faction_id, character_id] -- the inheritance chain, for provenance
    must_have: list[Atom]
    must_not: list[MustNot]
    identity_refs: list[IdentityRef]

    @model_validator(mode="after")
    def _check_unique_atom_ids(self) -> ResolvedContract:
        _reject_duplicate_ids(self.must_have, self.must_not, contract_id=self.id)
        return self

    @model_validator(mode="after")
    def _check_depends_on_edges(self) -> ResolvedContract:
        """Every dependency edge resolves, and the edges form a DAG.

        Referential first, deliberately: a dangling parent gets the error that names the
        missing id, rather than being reported as a stray root by the cycle walk.
        """
        _reject_unknown_depends_on(self.must_have, self.must_not, contract_id=self.id)
        _reject_cyclic_depends_on(self.must_have, self.must_not, contract_id=self.id)
        return self

    def required_atoms(self) -> list[Atom]:
        return [a for a in self.must_have if a.severity == Severity.required]

    def atom_by_id(self, atom_id: str) -> Atom | None:
        return next((a for a in self.must_have if a.id == atom_id), None)
