"""The Contract: a typed spec of atomic *depictable* claims — NOT a prose prompt.

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
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...errors import PromptCraftError


class CheckType(str, Enum):
    """Selects which gate tier verifies an atom (cheapest first)."""

    siglip2 = "siglip2"  # Tier-0: cheap closed-set / presence screen (sigmoid, per-query)
    vqa = "vqa"  # Tier-1: compositional VQAScore P('Yes')
    palette = "palette"  # deterministic colour check (no model)


class Severity(str, Enum):
    required = "required"  # a required atom blocks bind on failure (andon)
    optional = "optional"  # an optional atom only warns


class SpatialKind(str, Enum):
    region = "region"  # a named image region (torso, head, hands, chest-center)
    pose = "pose"  # a ControlNet pose/openpose reference image that locks geometry


class Spatial(BaseModel):
    """Where an atom must hold. ``region`` -> a checkable image region; ``pose`` -> a ControlNet ref
    that the generator uses to *lock* geometry (text cannot place 'axe in right hand'; the guide can)."""

    model_config = ConfigDict(extra="forbid")
    kind: SpatialKind
    ref: str  # region name, or a path to an openpose/controlnet image for kind=pose


class Atom(BaseModel):
    """One atomic depictable claim. The same atom list is used twice — to synthesize and to gate."""

    model_config = ConfigDict(extra="forbid")
    id: str
    claim: str  # a single visible claim, phrased as a checkable statement
    check_type: CheckType
    severity: Severity = Severity.required
    depends_on: str | None = None  # DAG edge: this atom is only meaningful if the parent passes
    spatial: Spatial | None = None
    enum: list[str] | None = None  # closed set for siglip2/palette atoms


class MustNot(BaseModel):
    """An anti-constraint, GATE-ENFORCED on the pixels (inverted probe) — NOT a negative prompt.

    Negative prompts / concept-erasure leave residual features and fall to paraphrase; satisfaction
    requires the gate to confirm *absence* on the actual pixels.

    ``severity`` exists because **a negation's blocking power should match the evidence behind the
    check that enforces it.** Confirming a thing is *absent* is a different capability from
    confirming a thing is present, and it is the less established of the two: CLIP-family encoders
    are documented as limited at negation (TNG-CLIP, arXiv:2505.18434, citation-gated `supported`),
    and no located source benchmarks a sigmoid zero-shot score as an absence verifier at all.

    A negation whose verifier is calibrated for absence earns ``required`` and blocks a bind. One
    whose verifier is not yet measured on absence is ``optional``: it still runs, still scores, and
    still rides the transcript — it simply does not assert more certainty than its evidence
    supports. This is the same principle as ``Zone.UNAVAILABLE`` and the could-not-run exit code:
    the system's claims track what it actually established.

    The default stays ``required``, so a contract written before this field means what it always
    meant. Promotion is the intended direction — measure the verifier on absence, then raise the
    severity with the measurement in hand."""

    model_config = ConfigDict(extra="forbid")
    id: str
    claim: str
    check_type: CheckType = CheckType.vqa
    severity: Severity = Severity.required
    enum: list[str] | None = None


class IdentityRef(BaseModel):
    """Identity = CONDITIONING, never tokens. A reference plate bound by LoRA / IP-Adapter.

    The proven-correct path: anatomical tokens make diffusion render specimens; a reference image
    binds the exact face/insignia, and the gate then verifies it rendered."""

    model_config = ConfigDict(extra="forbid")
    plate: str  # path to the reference plate image (the conditioning input)
    method: str = "ip_adapter"  # ip_adapter | instantid | lora | none
    weight: float = 0.6
    scope: str = "face"  # face | costume | silhouette | full


def _reject_duplicate_ids(
    must_have: Sequence[Atom], must_not: Sequence[MustNot], *, contract_id: str
) -> None:
    """Fail closed on a repeated atom id within one list (F-fb7194d3).

    ``QuestionDAG.topological()`` (``compile_questions.py``) keys its dependency walk purely
    by ``atom_id``: its ``index`` dict comprehension keeps the LAST atom with a given id, but
    its ``done`` set keeps the FIRST — so a duplicate id silently vanishes from the compiled
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
                    "contract. A duplicate is not deterministically evaluated — "
                    "QuestionDAG.topological() silently keeps only one declaration "
                    "and drops the rest."
                ),
            )
        seen.add(atom.id)


class Contract(BaseModel):
    """A single faction or character contract (unresolved — ``extends`` not yet applied)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    schema_id: str = Field(default="prompt-craft/contract.v1", alias="$schema")
    id: str
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

    @model_validator(mode="after")
    def _check_unique_atom_ids(self) -> Contract:
        _reject_duplicate_ids(self.must_have, self.must_not, contract_id=self.id)
        return self


class ResolvedContract(BaseModel):
    """A character contract with its faction base merged in (output of ``loader.resolve``).

    ``identity_refs`` is a LIST: the faction costume plate composes with the character face plate."""

    model_config = ConfigDict(extra="forbid")
    id: str
    level: str
    lineage: list[str]  # [faction_id, character_id] — the inheritance chain, for provenance
    must_have: list[Atom]
    must_not: list[MustNot]
    identity_refs: list[IdentityRef]

    @model_validator(mode="after")
    def _check_unique_atom_ids(self) -> ResolvedContract:
        _reject_duplicate_ids(self.must_have, self.must_not, contract_id=self.id)
        return self

    def required_atoms(self) -> list[Atom]:
        return [a for a in self.must_have if a.severity == Severity.required]

    def atom_by_id(self, atom_id: str) -> Atom | None:
        return next((a for a in self.must_have if a.id == atom_id), None)
