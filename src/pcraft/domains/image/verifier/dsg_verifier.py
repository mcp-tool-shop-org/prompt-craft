"""Tier-2 verifier: DSG per-atom DAG localization.

Runs only on a Tier-1 fail/borderline, to localize *which* atom failed. DSG decomposes a claim into
a dependency graph of yes/no questions; a NO parent forces NO on descendants (the harness already
enforces the DAG ordering — this verifier answers the localized per-atom probe). The question-
generation LM should be a DIFFERENT family from the VQA answerer; both are pinned. Lazy + graceful
(returns None when unavailable -> SKIPPED)."""

from __future__ import annotations

from ....core.contract.compile_questions import Question


class DSGVerifier:
    family = "dsg-qg"
    tier = 2
    verifier_id = "dsg.localizer.v1"
    version = "dsg-v1"

    def __init__(self, answerer_model: str = "clip-flant5-xxl", qg_model: str = "pinned-qg-lm"):
        self.answerer_model = answerer_model
        self.qg_model = qg_model  # MUST differ in family from the VQA answerer
        self._answerer = None
        self._unavailable = False

    def _get_answerer(self):
        if self._answerer is None and not self._unavailable:
            try:
                import t2v_metrics  # type: ignore

                self._answerer = t2v_metrics.VQAScore(model=self.answerer_model)
            except Exception:
                self._unavailable = True
        return self._answerer

    def score(self, image_path: str, question: Question) -> float | None:
        answerer = self._get_answerer()
        if answerer is None:
            return None
        # Per-atom localized probe. (A full DSG run would expand `question` into its sub-DAG via the
        # pinned QG LM; here the single localized atom probe is answered by the distinct-family VQA.)
        result = answerer(images=[image_path], texts=[question.text])
        return float(result[0][0])
