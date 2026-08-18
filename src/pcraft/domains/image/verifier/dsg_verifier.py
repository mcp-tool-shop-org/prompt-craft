"""Tier-2 verifier: DSG per-atom DAG localization.

Runs only on a Tier-1 fail/borderline, to localize *which* atom failed. DSG decomposes a claim into
a dependency graph of yes/no questions; a NO parent forces NO on descendants (the harness already
enforces the DAG ordering — this verifier answers the localized per-atom probe). The question-
generation LM should be a DIFFERENT family from the VQA answerer; both are pinned. Lazy + graceful
(returns None when unavailable -> SKIPPED).

HONESTY NOTE (F-721a7139): ``qg_model`` is not wired to anything -- no DAG expansion happens, no
sub-questions are generated. ``_get_answerer()`` calls the *same* ``t2v_metrics.VQAScore`` with the
*same default model id* (``vqascore_verifier.DEFAULT_MODEL_ID``) that Tier-1 (``VQAScoreVerifier``)
uses. Today, Tier-1 and Tier-2 differ only in their ``family`` LABEL ('clip-flant5' vs 'dsg-qg'); the
scoring computation is the same VQA model asked essentially the same question -- a family_guard-style
check that trusted the ``family`` string as proof of independence would be fooled. Real question
decomposition via ``qg_model`` is feature-pass work (a pinned QG LM, GPU, Director spend) and is out
of scope for this pass. What this pass does instead: make the sharing impossible to miss from
outside this file via ``shares_model_with`` rather than only a comment nobody has to read.

HONESTY NOTE (F-dd568f7f / F-2ef1bb79): the lazy-load / call-time exception handling follows the same
extras-missing-vs-genuine-failure split as the other verifiers in this domain — see
``siglip2_screen.py`` / ``vqascore_verifier.py``."""

from __future__ import annotations

import logging

from ....core.contract.compile_questions import Question
from ....errors import PromptCraftError
from .vqascore_verifier import DEFAULT_MODEL_ID as _VQA_TIER1_DEFAULT_MODEL_ID

_LOG = logging.getLogger(__name__)


class DSGVerifier:
    family = "dsg-qg"
    tier = 2
    verifier_id = "dsg.localizer.v1"
    version = "dsg-v1"

    def __init__(self, answerer_model: str = _VQA_TIER1_DEFAULT_MODEL_ID, qg_model: str = "pinned-qg-lm"):
        self.answerer_model = answerer_model
        self.qg_model = qg_model  # MUST differ in family from the VQA answerer -- NOT YET WIRED. No
        # DAG expansion reads this; see the HONESTY NOTE above (F-721a7139).
        self._answerer = None
        self._unavailable = False
        # F-721a7139: surfaced, not hidden behind the `family="dsg-qg"` label. None when this
        # instance's answerer_model differs from Tier-1's default (i.e. a real distinct model was
        # configured); otherwise the Tier-1 verifier_id this tier is, today, computationally
        # identical to.
        self.shares_model_with: str | None = (
            "vqascore.clip-flant5.v1" if answerer_model == _VQA_TIER1_DEFAULT_MODEL_ID else None
        )

    def _get_answerer(self):
        if self._answerer is None and not self._unavailable:
            try:
                import t2v_metrics  # type: ignore
            except ImportError:
                self._unavailable = True
                return None
            try:
                self._answerer = t2v_metrics.VQAScore(model=self.answerer_model)
            except Exception as err:
                _LOG.debug("DSGVerifier: answerer construction failed for model=%r: %s", self.answerer_model, err, exc_info=True)
                raise PromptCraftError(
                    "RUNTIME_VERIFIER_INIT_FAILED",
                    f"DSG answerer failed to construct (model={self.answerer_model!r}): {err}",
                    hint="This is not a missing t2v_metrics extra -- construction itself failed "
                    "(bad model id, corrupted checkpoint, CUDA OOM at load, ...). Check the cause.",
                    cause=err,
                ) from err
        return self._answerer

    def score(self, image_path: str, question: Question) -> float | None:
        answerer = self._get_answerer()
        if answerer is None:
            return None
        try:
            # Per-atom localized probe. (A full DSG run would expand `question` into its sub-DAG via
            # the pinned QG LM; today the single localized atom probe is answered directly -- by the
            # SAME model Tier-1 uses when answerer_model is left at its default; see
            # `shares_model_with`.)
            result = answerer(images=[image_path], texts=[question.text])
            return float(result[0][0])
        except Exception as err:
            _LOG.debug("DSGVerifier: call-time failure scoring atom %r: %s", question.atom_id, err, exc_info=True)
            raise PromptCraftError(
                "RUNTIME_VERIFIER_CALL_FAILED",
                f"DSG answerer raised while scoring atom {question.atom_id!r}: {err}",
                hint="The answerer constructed fine; the failure happened during the actual scoring "
                "call (bad image path, CUDA OOM mid-run, ...). This is distinct from SKIPPED -- the "
                "tier had a chance to run and blew up mid-question.",
                cause=err,
            ) from err
