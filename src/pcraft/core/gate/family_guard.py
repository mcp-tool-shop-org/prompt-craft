"""EXTERNAL_VERIFIER hard guard: never the same family, which includes never the same weights.

``assert_distinct_families`` hard-refuses if the generator family equals any gate
verifier family after ``normalize_family``. That is rule (2) in
``verifier_iface.py`` — sibling checkpoints cannot sneak past (the
``google/siglip2-*`` line is one family for that reason).

It is not a ban on generative verifiers. A generative VLM scoring an SDXL
image is a different family and passes this guard. Two generative VLMs
currently share the ``generative-vlm`` token, so they do not pass. See
``verifier_iface.py`` for the slogan-vs-rule writeup.

Earned on this rig: a generative VLM (LLaVA-13B) hallucinated greatswords on
unarmed cooks at 0.90 confidence (P=0.26); the discriminative, different-family
SigLIP2 scored P=0.909. That measurement is same-object-presence, two families
— it supports (2), not a blanket ban on generative scoring of diffusion output.
"""

from __future__ import annotations

import re

from ...errors import PromptCraftError

# Normalization rules: map concrete model ids/families onto a coarse family token.
_FAMILY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"siglip", re.IGNORECASE), "siglip"),
    (re.compile(r"clip[-_]?flan[-_]?t5|vqascore", re.IGNORECASE), "clip-flant5"),
    (re.compile(r"\bsdxl\b|stable[-_]?diffusion|\bsd[-_]?\d", re.IGNORECASE), "stable-diffusion"),
    (re.compile(r"\bflux\b", re.IGNORECASE), "flux"),
    (re.compile(r"llava|qwen[-_]?vl|internvl|gpt-?4v|gemini", re.IGNORECASE), "generative-vlm"),
    (re.compile(r"\bdsg\b|question[-_]?gen", re.IGNORECASE), "dsg-qg"),
    (re.compile(r"\bclip\b", re.IGNORECASE), "clip"),  # bare CLIP last, so siglip/flant5 win above
]


def normalize_family(name: str) -> str:
    """Collapse a model id or family string to a coarse family token. Unknown -> the lowered string."""
    for pattern, family in _FAMILY_RULES:
        if pattern.search(name):
            return family
    return name.strip().lower()


def assert_distinct_families(generator_family: str, verifier_families: list[str]) -> None:
    """Raise GATE_SAME_FAMILY if the generator shares a normalized family with any gate verifier.

    ``verifier_families`` must be a sequence of names, not a bare string. Iterating a
    string checks characters (``'sdxl'`` → ``s,d,x,l``), none of which normalize to
    the generator family, so the one case this guard exists to refuse would pass.
    """
    if isinstance(verifier_families, (str, bytes)):
        raise PromptCraftError(
            "GATE_FAMILIES_NOT_A_LIST",
            # F-a6acaab1: the U+2014 here was missed for the same reason as exit_contract's --
            # it is a message argument, not a DEFAULT_HINTS value, and the wave-2 sweep only
            # looked at the hints table.
            f"verifier_families must be a list of family names, not {type(verifier_families).__name__} "
            f"{verifier_families!r} -- iterating a string checks characters and the guard cannot fire",
        )
    gen = normalize_family(generator_family)
    for vf in verifier_families:
        if normalize_family(vf) == gen:
            raise PromptCraftError(
                "GATE_SAME_FAMILY",
                f"generator family {generator_family!r} == verifier family {vf!r} "
                f"(both normalize to {gen!r})",
            )
