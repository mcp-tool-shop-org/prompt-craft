"""The Verifier plugin interface, and the CLIPScore ban.

A Verifier scores how strongly a rendered image satisfies one question, returning a float in
[0, 1] (or ``None`` to signal *unavailable* — the harness records SKIPPED, never a silent pass).

CLIPScore is BANNED as the gate metric: it is a bag-of-concepts cosine, blind to attribute binding,
counts, and relations — exactly the failures the contract gate exists to catch. ``forbid_clipscore``
rejects any verifier that advertises CLIPScore as its family, so nobody reintroduces it."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...errors import PromptCraftError
from ..contract.compile_questions import Question

# Families that may never be registered as the gate metric.
BANNED_GATE_FAMILIES = {"clipscore", "clip-score", "clip_cosine"}


@runtime_checkable
class Verifier(Protocol):
    """A scoring instrument over (image, question). Distinct *family* from the generator."""

    verifier_id: str
    version: str
    family: str  # e.g. "siglip2", "clip-flant5", "dsg-qg" — must differ from the generator family
    tier: int  # 0 cheap screen, 1 compositional, 2 per-atom localization

    def score(self, image_path: str, question: Question) -> float | None:
        """Return P(question is satisfied) in [0,1], or None if this verifier cannot answer
        (e.g. its model is not installed). None => the harness records SKIPPED for this atom."""
        ...


def forbid_clipscore(verifier: Verifier) -> None:
    """Raise if a verifier advertises a banned (CLIPScore-family) gate metric."""
    fam = verifier.family.strip().lower()
    if fam in BANNED_GATE_FAMILIES:
        raise PromptCraftError(
            "GATE_CLIPSCORE_BANNED",
            f"verifier {verifier.verifier_id!r} uses banned gate family {verifier.family!r}",
        )
