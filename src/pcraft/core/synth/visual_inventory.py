"""The visual_inventory scratchpad and the anti-prose-dump guard.

Reason-before-write: each contract atom becomes an inventory row tagged ``depictable`` with a
``front_load_rank`` and a single ``token`` (its depictable phrase). A real 600B synthesizer also
emits rows for backstory / emotion / intent and marks them ``depictable=False`` so they are pruned
*before* the prompt is composed.

The guard -- ``assert_tokens_trace`` -- enforces the single strongest rule against the model's
prose-dumping tendency: **every content token in the final prompt must trace to a depictable
inventory row** (render/style boilerplate is the only other thing allowed). An injected
"epic cinematic masterpiece, trending on artstation" has no atom behind it and is rejected."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ...errors import PromptCraftError
from ..contract.schema import ResolvedContract, Severity

# Render/style direction that is NOT an identity atom -- the only non-atom tokens a prompt may carry.
# (From the supersession audit: do NOT turn 'front-facing view'/'plain white background' into atoms.)
#
# [!] THE FALLBACK, not the only source (F-c6b06c2f). These five tokens are sprite/image
# phrasing sitting at DOMAIN-AGNOSTIC module scope, so every domain's TemplateSynthesizer
# output carried them -- including a video or audio domain that has no "background" to isolate
# anything on. A DomainPlugin's encoder-rules file may now declare its own set; see
# parse_render_boilerplate. What did NOT change is their status: boilerplate stays outside the
# contract schema, and stays inside assert_tokens_trace's allow-list. Only the SOURCE moved.
RENDER_BOILERPLATE: list[str] = [
    "full body visible",
    "front-facing view",
    "isolated on plain white background",
    "character concept art",
    "clean sharp lines",
]

_BOILERPLATE_OPEN = "<!-- pcraft:render_boilerplate -->"
_BOILERPLATE_CLOSE = "<!-- /pcraft:render_boilerplate -->"
"""The marked block a domain's encoder-rules file uses to declare its own boilerplate.

An HTML comment because those files are generated Markdown (``domains/image/rules/
encoder_craft.md`` is 300KB of it) -- so the block is invisible when the rules are read as
documentation, and unambiguous when they are parsed. Verified absent from the shipped rules
file, which is what makes the fallback below the observed behaviour rather than a hope."""


def parse_render_boilerplate(encoder_rules: str | None) -> list[str]:
    """The domain's boilerplate tokens, or ``RENDER_BOILERPLATE`` when it declares none.

    ABSENT and EMPTY are different answers, deliberately:

    * no block at all (and ``""``, and ``None``) -> the literal default above. Every caller
      shipping today is in this arm -- the ``""`` the synth tests pass and the generated
      ``encoder_craft.md``, which carries no block -- so their prompts are byte-for-byte
      unchanged by this parameter becoming live.
    * a block with no entries -> ``[]``. A domain saying "I have none" is the case that
      motivated the finding, and silence must not be read as that decision.

    Entries are one per line, with an optional ``-``/``*`` bullet; blank lines and ``#``
    comment lines inside the block are skipped.
    """
    text = encoder_rules or ""
    start = text.find(_BOILERPLATE_OPEN)
    if start < 0:
        return list(RENDER_BOILERPLATE)
    start += len(_BOILERPLATE_OPEN)
    end = text.find(_BOILERPLATE_CLOSE, start)
    block = text[start:] if end < 0 else text[start:end]
    tokens: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens.append(line.lstrip("-*").strip())
    return [t for t in tokens if t]


class InventoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str
    depictable: bool
    front_load_rank: int
    token: str
    note: str = ""


def build_inventory(
    resolved: ResolvedContract, *, boost_ids: list[str] | None = None
) -> list[InventoryRow]:
    """One row per must_have atom. Front-load required + independent (presence) atoms first.

    ``boost_ids`` is the RESYNTH lever: failed atoms drop 1000 ranks so they lead
    the prompt. A seed bump without this is not a re-synthesize.
    """
    boost = set(boost_ids or [])
    rows: list[InventoryRow] = []
    for index, atom in enumerate(resolved.must_have):
        rank = (0 if atom.severity is Severity.required else 100)
        rank += (0 if atom.depends_on is None else 10)  # dependents after their parents
        rank += index
        if atom.id in boost:
            rank -= 1000
        rows.append(
            InventoryRow(
                atom_id=atom.id,
                depictable=True,  # every must_have atom is a visible claim by construction
                front_load_rank=rank,
                token=atom.claim,
                note="resynth-boost" if atom.id in boost else "",
            )
        )
    return rows


def _normalize(seg: str) -> str:
    return " ".join(seg.lower().split()).strip(" .,")


def assert_tokens_trace(
    prompt: str, inventory: list[InventoryRow], *, boilerplate: list[str] | None = None
) -> None:
    """Raise SYNTH_PROSE_DUMP if any comma-separated prompt segment traces to neither a depictable
    inventory token nor the render-boilerplate allowlist.

    ``boilerplate`` is the allow-list's second half, defaulting to ``RENDER_BOILERPLATE`` so
    every existing caller is unaffected. A caller whose synthesizer used domain-declared
    boilerplate passes the SAME list here (``parse_render_boilerplate(encoder_rules)``) --
    which is the point: domain-supplied tokens are ALLOW-LISTED, never exempt. A prompt built
    from one domain's boilerplate is still refused under another's, and prose that traces to
    neither an atom nor the list in force is refused under both.
    """
    depictable_tokens = {_normalize(r.token) for r in inventory if r.depictable}
    allowed_boilerplate = RENDER_BOILERPLATE if boilerplate is None else boilerplate
    allowed = depictable_tokens | {_normalize(b) for b in allowed_boilerplate}
    untraceable: list[str] = []
    for seg in prompt.split(","):
        norm = _normalize(seg)
        if not norm:
            continue
        if norm in allowed:
            continue
        # A segment that is a fragment of a known token (norm in tok) is the
        # intended looseness: "tabard" traces to "a grey-ash tabard worn...".
        # tok in norm is the other direction -- extra words around a full claim.
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
