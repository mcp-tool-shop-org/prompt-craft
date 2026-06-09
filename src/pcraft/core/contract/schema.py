"""The Contract: a typed spec of atomic *depictable* claims — NOT a prose prompt.

This replaces the opaque ``{name, prompt, weapon_class}`` triple that prompt-craft supersedes,
and it is a typed pydantic transcription of style-dataset-lab's identity-gates spec
(non_negotiable_details -> must_have, forbidden_drift_cues -> must_not, reference plate ->
identity_ref). Prose prompts are a *derived, regenerable* artifact (see ``synth/``); they never
live in the contract.

Two levels with inheritance: a ``faction`` is the base class; a ``character`` ``extends`` a faction
and may ADD or RAISE requirements but may never drop or relax a faction-required atom
(enforced fail-closed in ``loader.py``).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


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
    requires the gate to confirm *absence* on the actual pixels."""

    model_config = ConfigDict(extra="forbid")
    id: str
    claim: str
    check_type: CheckType = CheckType.vqa
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


class Contract(BaseModel):
    """A single faction or character contract (unresolved — ``extends`` not yet applied)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    schema_id: str = Field(default="prompt-craft/contract.v1", alias="$schema")
    id: str
    level: str  # "faction" | "character"
    extends: str | None = None  # a faction id, for level == "character"
    must_have: list[Atom] = Field(default_factory=list)
    must_not: list[MustNot] = Field(default_factory=list)
    identity_ref: IdentityRef | None = None


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

    def required_atoms(self) -> list[Atom]:
        return [a for a in self.must_have if a.severity == Severity.required]

    def atom_by_id(self, atom_id: str) -> Atom | None:
        return next((a for a in self.must_have if a.id == atom_id), None)
