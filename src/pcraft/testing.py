"""Deterministic reference implementations for the GPU-free demo and the core test suite.

These are NOT the real generator/verifier — they are the mocks that prove the plugin boundary holds:
the entire synth->generate->gate->retry->bind loop runs with no torch, no diffusion, no network.
``StubGenerator`` writes a real (tiny, solid-colour) PNG so "look at the output" yields a viewable
file; ``ScriptedVerifier`` returns programmable scores so PASS/FAIL/retry scenarios are deterministic."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable
from pathlib import Path

from .core.contract.compile_questions import Polarity, Question
from .core.gate.verifier_iface import Verifier
from .core.loop.generator_iface import GenerationResult


def write_solid_png(path: str | Path, rgb: tuple[int, int, int] = (58, 58, 58), size: int = 64) -> Path:
    """Write a minimal valid solid-colour PNG (pure stdlib — no Pillow)."""
    w = h = size
    row = bytes([0]) + bytes(rgb) * w  # filter byte 0 + RGB pixels
    raw = row * h

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))  # 8-bit RGB
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(png)
    return p


class StubGenerator:
    """GPU-free generator. Family normalizes to 'stable-diffusion' (so family_guard treats it like
    the real SDXL generator and refuses a SigLIP/SD-family verifier)."""

    generator_id = "stub.sdxl.v0"
    family = "stable-diffusion"

    def __init__(self, out_dir: str | Path = "records/_stub_images", color: tuple[int, int, int] = (58, 58, 58)):
        self.out_dir = Path(out_dir)
        self.color = color

    def generate(self, prompt: str, negative_prompt: str, conditioning: dict, seed: int) -> GenerationResult:
        # INPAINT_REGION keeps the seed and varies the file so the named action is
        # not a byte-identical regenerate of stub_seed{N}.png.
        suffix = "_inpaint" if conditioning.get("inpaint_from") else ""
        path = write_solid_png(self.out_dir / f"stub_seed{seed}{suffix}.png", self.color)
        return GenerationResult(
            image_path=str(path),
            seed=seed,
            sampler="ddim-stub-30",
            generator_id=self.generator_id,
            generator_family=self.family,
            conditioning=conditioning,
        )


class ScriptedVerifier:
    """A verifier whose scores are programmable. By default every affirm probe passes (0.95) and
    every must_not (negate) probe reads clearly absent (0.005, below even the strict siglip2 floor),
    so the default scenario binds cleanly; pass a
    ``scores`` dict (atom_id -> score) or a callable to script a failure."""

    def __init__(
        self,
        scores: dict[str, float] | Callable[[Question], float] | None = None,
        *,
        family: str = "clip-flant5",
        tier: int = 1,
        verifier_id: str = "scripted.vqa.v0",
        version: str = "v0",
    ):
        self._scores = scores or {}
        self.family = family
        self.tier = tier
        self.verifier_id = verifier_id
        self.version = version

    def score(self, image_path: str, question: Question) -> float | None:
        if callable(self._scores):
            return self._scores(question)
        if question.atom_id in self._scores:
            return self._scores[question.atom_id]
        return 0.005 if question.polarity is Polarity.negate else 0.95


def passing_verifiers(**kwargs) -> dict[int, Verifier]:
    """Tier-0 + Tier-1, different-family verifiers, so the harness actually EXECUTES both
    required tiers instead of relying on ``_pick``'s tier-1 fallback for Tier-0-designated
    (siglip2/palette) atoms.

    A single registered Tier-1 verifier still scores every atom -- ``_pick`` falls forward
    from tier 0 to tier 1 when tier 0 is absent -- so the gate's own verdict was never
    wrong. But ``_tier_census`` only credits the tier a score actually ``tier_used``, so a
    demo/bind run that never registers Tier-0 reports ``tiers executed: 1 of 2`` under a
    clean BOUND/PASS decision: the mock cannot tell "the gate ran fully" apart from "half
    the gate never ran", because it never truly ran the half it claims credit for
    (F-834dd470). Registering a real Tier-0 verifier here closes that gap without
    changing any default score (both verifiers still pass-everything by default), so
    every existing PASS/BOUND scenario keeps its verdict -- only the census becomes
    honest.
    """
    v0 = ScriptedVerifier(family="siglip2", tier=0, verifier_id="scripted.siglip2.v0", **kwargs)
    v1 = ScriptedVerifier(**kwargs)  # defaults: family=clip-flant5, tier=1, id=scripted.vqa.v0
    return {v0.tier: v0, v1.tier: v1}
