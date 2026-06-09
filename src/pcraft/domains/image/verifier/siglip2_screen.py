"""Tier-0 verifier: SigLIP2 cheap closed-set / presence screen.

Reuses the ai-eyes-mcp ``SigLIPEngine`` (the private, measured-on-rig instrument) — we do NOT
reimplement the SigLIP2 forward pass, sigmoid scoring, or calibration. The score is an INDEPENDENT
sigmoid per query (not a softmax). If the engine is unavailable (the ``[image]`` extra or the
ai-eyes repo isn't installed), the screen SKIPS gracefully — the harness records SKIPPED, never a
silent pass. ``family = "siglip2"`` so family_guard treats the whole ``google/siglip2-*`` line as one
family."""

from __future__ import annotations

from ....core.contract.compile_questions import Question


class SigLIP2Screen:
    family = "siglip2"
    tier = 0
    verifier_id = "siglip2.screen.v1"
    version = "so400m-patch14-384"

    def __init__(self, model_id: str = "google/siglip2-so400m-patch14-384", threshold: float = 0.02):
        self.model_id = model_id
        self.threshold = threshold
        self._engine = None
        self._unavailable = False

    def _get_engine(self):
        if self._engine is None and not self._unavailable:
            try:
                # the canonical SigLIP2 instrument — import, never reimplement
                from ai_eyes_mcp.engine import SigLIPEngine  # type: ignore

                self._engine = SigLIPEngine(model_id=self.model_id)
            except Exception:
                self._unavailable = True  # graceful degradation: Tier-0 SKIPS, never crashes the run
        return self._engine

    def score(self, image_path: str, question: Question) -> float | None:
        engine = self._get_engine()
        if engine is None:
            return None  # SKIPPED — distinct from a fail
        return float(engine.score(image_path, question.text))
