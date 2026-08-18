"""Tier-1 verifier: VQAScore (CLIP-FlanT5 P('Yes')).

VQAScore answers "Does this image show {claim}?" and returns P('Yes') in one forward pass — it binds
attributes, counts, and relations (the things CLIPScore is blind to). ``family = "clip-flant5"``,
distinct from both the SDXL generator and the SigLIP2 screen. Lazy + graceful: if the model isn't
installed, returns None (SKIPPED).

HONESTY NOTE (F-dd568f7f / F-2ef1bb79): "the extra isn't installed" and "the extra IS installed but
construction/scoring blew up for an unrelated reason" used to collapse into the same SKIPPED outcome
via a bare ``except Exception``. Only the former is SKIPPED now; the latter raises a classified
``PromptCraftError`` (distinct code, real cause attached, logged) instead of masquerading as
"dependency not installed"."""

from __future__ import annotations

import logging

from ....core.contract.compile_questions import Question
from ....errors import PromptCraftError

_LOG = logging.getLogger(__name__)

# The Tier-1 default model id. Named here (rather than only inline as a constructor default) so
# DSGVerifier (Tier-2) can compare its own answerer_model against this exact value and surface it
# honestly when the two tiers are, today, running the identical VQA model -- see F-721a7139.
DEFAULT_MODEL_ID = "clip-flant5-xxl"


class VQAScoreVerifier:
    family = "clip-flant5"
    tier = 1
    verifier_id = "vqascore.clip-flant5.v1"
    version = "clip-flant5-xxl"

    def __init__(self, model_id: str = DEFAULT_MODEL_ID):
        self.model_id = model_id
        self._scorer = None
        self._unavailable = False

    def _get_scorer(self):
        if self._scorer is None and not self._unavailable:
            try:
                import t2v_metrics  # type: ignore
            except ImportError:
                self._unavailable = True
                return None
            try:
                self._scorer = t2v_metrics.VQAScore(model=self.model_id)
            except Exception as err:
                _LOG.debug("VQAScoreVerifier: scorer construction failed for model=%r: %s", self.model_id, err, exc_info=True)
                raise PromptCraftError(
                    "RUNTIME_VERIFIER_INIT_FAILED",
                    f"VQAScore scorer failed to construct (model={self.model_id!r}): {err}",
                    hint="This is not a missing t2v_metrics extra -- construction itself failed "
                    "(bad model id, corrupted checkpoint, CUDA OOM at load, ...). Check the cause.",
                    cause=err,
                ) from err
        return self._scorer

    def score(self, image_path: str, question: Question) -> float | None:
        scorer = self._get_scorer()
        if scorer is None:
            return None
        try:
            # VQAScore takes the bare claim; it forms "Does this image show {text}? Yes/No" internally.
            result = scorer(images=[image_path], texts=[question.text])
            return float(result[0][0])
        except Exception as err:
            _LOG.debug("VQAScoreVerifier: call-time failure scoring atom %r: %s", question.atom_id, err, exc_info=True)
            raise PromptCraftError(
                "RUNTIME_VERIFIER_CALL_FAILED",
                f"VQAScore scorer raised while scoring atom {question.atom_id!r}: {err}",
                hint="The scorer constructed fine; the failure happened during the actual scoring "
                "call (bad image path, CUDA OOM mid-run, ...). This is distinct from SKIPPED -- the "
                "tier had a chance to run and blew up mid-question.",
                cause=err,
            ) from err
