"""EXTERNAL_VERIFIER hard guard: a model must never be its own gate.

``assert_distinct_families`` hard-refuses to run if the generator family equals any gate verifier
family. Earned on this rig: a generative VLM (LLaVA-13B) hallucinated greatswords on unarmed cooks
at 0.90 confidence (P=0.26); the discriminative, different-family SigLIP2 scored P=0.909. The whole
``google/siglip2-*`` line normalizes to one family so a sibling checkpoint can't sneak past."""

from __future__ import annotations

import re

from ...errors import PromptCraftError

# Normalization rules: map concrete model ids/families onto a coarse family token.
_FAMILY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"siglip", re.I), "siglip"),
    (re.compile(r"clip[-_]?flan[-_]?t5|vqascore", re.I), "clip-flant5"),
    (re.compile(r"\bsdxl\b|stable[-_]?diffusion|\bsd[-_]?\d", re.I), "stable-diffusion"),
    (re.compile(r"\bflux\b", re.I), "flux"),
    (re.compile(r"llava|qwen[-_]?vl|internvl|gpt-?4v|gemini", re.I), "generative-vlm"),
    (re.compile(r"\bdsg\b|question[-_]?gen", re.I), "dsg-qg"),
    (re.compile(r"\bclip\b", re.I), "clip"),  # bare CLIP last, so siglip/flant5 win above
]


def normalize_family(name: str) -> str:
    """Collapse a model id or family string to a coarse family token. Unknown -> the lowered string."""
    for pattern, family in _FAMILY_RULES:
        if pattern.search(name):
            return family
    return name.strip().lower()


def assert_distinct_families(generator_family: str, verifier_families: list[str]) -> None:
    """Raise GATE_SAME_FAMILY if the generator shares a normalized family with any gate verifier."""
    gen = normalize_family(generator_family)
    for vf in verifier_families:
        if normalize_family(vf) == gen:
            raise PromptCraftError(
                "GATE_SAME_FAMILY",
                f"generator family {generator_family!r} == verifier family {vf!r} "
                f"(both normalize to {gen!r})",
            )
