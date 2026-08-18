"""The Verifier plugin interface, the CLIPScore ban, and the self-gate rule.

A Verifier scores how strongly a rendered image satisfies one question, returning a float in
[0, 1] (or ``None`` to signal *unavailable* — the harness records SKIPPED, never a silent pass).

CLIPScore is BANNED as the gate metric: it is a bag-of-concepts cosine, blind to attribute binding,
counts, and relations — exactly the failures the contract gate exists to catch. ``forbid_clipscore``
rejects any verifier that advertises CLIPScore as its family, so nobody reintroduces it.
Measured on CLIP (arXiv:2507.07985, supported); transfer to SigLIP2 is same-family and unconfirmed.

-----------------------------------------------------------------------------
GENERATIVE VERIFIER — the distinction, written down so it is not resolved by accident.

The studio slogan has been "a generative VLM is never its own gate." That sentence
collapses two rules:

  (1) Same weights: the model that painted the pixels does not score them.
  (2) Same family: a sibling checkpoint of the generator does not score them.

These differ. (1) alone would allow Qwen-VL to gate a LLaVA image. (2) is what
``family_guard`` actually enforces: ``normalize_family(generator) !=
normalize_family(verifier)`` for every verifier. LLaVA, Qwen-VL, InternVL,
GPT-4V and Gemini currently collapse to one token ``generative-vlm``, so two
different generative VLMs cannot verify each other under today's normalizer.
A generative VLM verifying a *diffusion* generator (SDXL, Flux) is a different
family and is admissible under (2). It is not banned by CLIPScore (a metric)
and it is not banned by (1) (different weights).

The slogan is convergent inference, not a measured head-to-head (POPE,
self-correction, self-preference; no paper runs one generative VLM against
one discriminative model on the same object-presence case). The enforceable
rule is (2): never the same family. Do not add a blanket ban on
``generative-vlm`` as a verifier of a diffusion generator without a
measurement that says so.

A *separate* generative verifier of a different family is therefore not a
silent violation. It is an open product call. This file is where that call
has to be written before anyone implements it.
-----------------------------------------------------------------------------
"""

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
