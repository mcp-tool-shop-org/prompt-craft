"""The visual_inventory scratchpad and the anti-prose-dump guard.

Reason-before-write: each contract atom becomes an inventory row tagged ``depictable`` with a
``front_load_rank`` and a single ``token`` (its depictable phrase). A real 600B synthesizer also
emits rows for backstory / emotion / intent and marks them ``depictable=False`` so they are pruned
*before* the prompt is composed.

The guard — ``assert_tokens_trace`` — enforces the single strongest rule against the model's
prose-dumping tendency: **every content token in the final prompt must trace to a depictable
inventory row** (render/style boilerplate is the only other thing allowed). An injected
"epic cinematic masterpiece, trending on artstation" has no atom behind it and is rejected."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ...errors import PromptCraftError
from ..contract.schema import ResolvedContract, Severity

# Render/style direction that is NOT an identity atom — the only non-atom tokens a prompt may carry.
# (From the supersession audit: do NOT turn 'front-facing view'/'plain white background' into atoms.)
RENDER_BOILERPLATE: list[str] = [
    "full body visible",
    "front-facing view",
    "isolated on plain white background",
    "character concept art",
    "clean sharp lines",
]


class InventoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str
    depictable: bool
    front_load_rank: int
    token: str
    note: str = ""


def build_inventory(resolved: ResolvedContract) -> list[InventoryRow]:
    """One row per must_have atom. Front-load required + independent (presence) atoms first."""
    rows: list[InventoryRow] = []
    for index, atom in enumerate(resolved.must_have):
        rank = (0 if atom.severity is Severity.required else 100)
        rank += (0 if atom.depends_on is None else 10)  # dependents after their parents
        rank += index
        rows.append(
            InventoryRow(
                atom_id=atom.id,
                depictable=True,  # every must_have atom is a visible claim by construction
                front_load_rank=rank,
                token=atom.claim,
            )
        )
    return rows


def _normalize(seg: str) -> str:
    return " ".join(seg.lower().split()).strip(" .,")


def assert_tokens_trace(prompt: str, inventory: list[InventoryRow]) -> None:
    """Raise SYNTH_PROSE_DUMP if any comma-separated prompt segment traces to neither a depictable
    inventory token nor the render-boilerplate allowlist."""
    depictable_tokens = {_normalize(r.token) for r in inventory if r.depictable}
    allowed = depictable_tokens | {_normalize(b) for b in RENDER_BOILERPLATE}
    untraceable: list[str] = []
    for seg in prompt.split(","):
        norm = _normalize(seg)
        if not norm:
            continue
        if norm in allowed:
            continue
        # A segment that is a fragment of a known token (norm in tok) is the
        # intended looseness: "tabard" traces to "a grey-ash tabard worn…".
        # tok in norm is the other direction — extra words around a full claim.
        # That arm is the same shape as the _is_identity_atom substring defect:
        # a short token ("a", "or", "art") is a substring of almost any English
        # segment. Only tokens long enough to be a phrase may match that way.
        if any(norm in tok or (len(tok) >= 8 and tok in norm) for tok in allowed):
            continue
        untraceable.append(seg.strip())
    if untraceable:
        raise PromptCraftError(
            "SYNTH_PROSE_DUMP",
            f"prompt has {len(untraceable)} token(s) that trace to no depictable atom: {untraceable}",
            hint="Every prompt token must come from a contract atom (or render boilerplate). "
            "Prune the un-depictable rows before composing the prompt.",
        )
