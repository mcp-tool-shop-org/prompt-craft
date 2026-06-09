"""Tier-1 verifier: VQAScore (CLIP-FlanT5 P('Yes')).

VQAScore answers "Does this image show {claim}?" and returns P('Yes') in one forward pass — it binds
attributes, counts, and relations (the things CLIPScore is blind to). ``family = "clip-flant5"``,
distinct from both the SDXL generator and the SigLIP2 screen. Lazy + graceful: if the model isn't
installed, returns None (SKIPPED)."""

from __future__ import annotations

from ....core.contract.compile_questions import Question


class VQAScoreVerifier:
    family = "clip-flant5"
    tier = 1
    verifier_id = "vqascore.clip-flant5.v1"
    version = "clip-flant5-xxl"

    def __init__(self, model_id: str = "clip-flant5-xxl"):
        self.model_id = model_id
        self._scorer = None
        self._unavailable = False

    def _get_scorer(self):
        if self._scorer is None and not self._unavailable:
            try:
                import t2v_metrics  # type: ignore

                self._scorer = t2v_metrics.VQAScore(model=self.model_id)
            except Exception:
                self._unavailable = True
        return self._scorer

    def score(self, image_path: str, question: Question) -> float | None:
        scorer = self._get_scorer()
        if scorer is None:
            return None
        # VQAScore takes the bare claim; it forms "Does this image show {text}? Yes/No" internally.
        result = scorer(images=[image_path], texts=[question.text])
        return float(result[0][0])
