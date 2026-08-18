"""Sprite cross-view identity sub-gate: CLIP-I consistency over the 8-direction turnaround.

After per-view contract gating, this catches silhouette/palette drift that per-image gates miss
across a turnaround: it requires the CLIP-I cosine (reference plate vs each rendered view) to clear a
floor AND show low cross-view variance. Failures route to reference-anchored inpaint, not a free
reroll. Metric per AnyCrowd (arXiv:2603.15415) — a multi-character/video CLIP-I consistency measure.

``similarity(a, b) -> cosine`` is injectable (mock-friendly); the default lazily uses the ai-eyes
SigLIP2 engine's ``compare``."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict


class SubGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    min_similarity: float
    mean_similarity: float
    variance: float
    per_view: dict[str, float]
    reason: str


class IdentitySubGate:
    verifier_id = "sprite.clip-i.subgate.v1"
    family = "siglip2"  # CLIP-I embeddings come from the SigLIP2 family

    def __init__(
        self,
        similarity: Callable[[str, str], float] | None = None,
        floor: float = 0.55,
        max_variance: float = 0.05,
    ):
        self._similarity = similarity
        self.floor = floor
        self.max_variance = max_variance
        self._engine = None
        self._unavailable = False

    def _sim(self, a: str, b: str) -> float | None:
        if self._similarity is not None:
            return self._similarity(a, b)
        if self._engine is None and not self._unavailable:
            try:
                from ai_eyes_mcp.engine import SigLIPEngine  # type: ignore

                self._engine = SigLIPEngine()
            except ImportError:
                # F-dd568f7f, narrowed per standing Director ruling on this file (no delete, no
                # promote, no wire into the loop -- floor/max_variance untouched, nothing else in
                # this file changed): only "the extra genuinely isn't installed" is SKIPPED now. A
                # genuine construction failure (bad ctor signature, CUDA OOM, ...) is no longer this
                # except clause's business -- it propagates instead of masquerading as "not installed".
                self._unavailable = True
        if self._engine is None:
            return None
        return float(self._engine.compare(a, b))

    def evaluate(self, plate_path: str, view_paths: dict[str, str]) -> SubGateResult | None:
        per_view: dict[str, float] = {}
        for direction, path in view_paths.items():
            sim = self._sim(plate_path, path)
            if sim is None:
                return None  # SKIPPED — embedder unavailable
            per_view[direction] = round(sim, 4)

        sims = list(per_view.values())
        mean = sum(sims) / len(sims)
        variance = sum((s - mean) ** 2 for s in sims) / len(sims)
        min_sim = min(sims)
        passed = min_sim >= self.floor and variance <= self.max_variance
        return SubGateResult(
            passed=passed,
            min_similarity=round(min_sim, 4),
            mean_similarity=round(mean, 4),
            variance=round(variance, 6),
            per_view=per_view,
            reason=(
                "ok"
                if passed
                else f"min CLIP-I {min_sim:.3f} (floor {self.floor}) / variance {variance:.4f} (max {self.max_variance})"
            ),
        )
