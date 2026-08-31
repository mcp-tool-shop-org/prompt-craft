"""Tier-0 verifier: SigLIP2 cheap closed-set / presence screen.

Reuses the ai-eyes-mcp ``SigLIPEngine`` (the private, measured-on-rig instrument) — we do NOT
reimplement the SigLIP2 forward pass, sigmoid scoring, or calibration. The score is an INDEPENDENT
sigmoid per query (not a softmax). If the engine is unavailable (the ``[image]`` extra or the
ai-eyes repo isn't installed), the screen SKIPS gracefully — the harness records SKIPPED, never a
silent pass. ``family = "siglip2"`` so family_guard treats the whole ``google/siglip2-*`` line as one
family.

HONESTY NOTE (F-dd568f7f / F-2ef1bb79): "the extra isn't installed" and "the extra IS installed but
construction/scoring blew up for an unrelated reason" used to collapse into the same SKIPPED outcome
via a bare ``except Exception``. Only the former is SKIPPED now; the latter raises a classified
``PromptCraftError`` (distinct code, real cause attached, logged) instead of masquerading as
"dependency not installed"."""

from __future__ import annotations

import logging

from ....core.contract.compile_questions import Question
from ....errors import PromptCraftError
from .region import full_frame_note

_LOG = logging.getLogger(__name__)


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
            except ImportError:
                self._unavailable = True  # graceful degradation: Tier-0 SKIPS, never crashes the run
                return None
            try:
                self._engine = SigLIPEngine(model_id=self.model_id)
            except Exception as err:
                _LOG.debug("SigLIP2Screen: engine construction failed for model_id=%r: %s", self.model_id, err, exc_info=True)
                raise PromptCraftError(
                    "RUNTIME_VERIFIER_INIT_FAILED",
                    f"SigLIP2 engine failed to construct (model_id={self.model_id!r}): {err}",
                    hint="This is not a missing [image]/ai-eyes extra -- construction itself failed "
                    "(bad model id, corrupted checkpoint, CUDA OOM at load, ...). Check the cause.",
                    cause=err,
                ) from err
        return self._engine

    def score_detail(self, image_path: str, question: Question) -> str | None:
        """Says so when this screen scored the whole frame for an atom that named a region.

        F-2c77d698, the scope half. The image domain's deterministic histogram now crops to
        ``spatial.kind=region`` before measuring; this screen does not, because its band
        (``siglip2`` 0.10/0.01) was derived on whole images and nothing here has measured what a
        sigmoid does to a 40%-of-frame crop. Partial support in silence is the worse outcome --
        the operator would have no way to tell which region atoms were actually localized -- so
        the gap rides the transcript through ``harness._detail_for`` until the measurement exists.
        """
        return full_frame_note(question, self.verifier_id)

    def score(self, image_path: str, question: Question) -> float | None:
        engine = self._get_engine()
        if engine is None:
            return None  # SKIPPED — distinct from a fail
        try:
            return float(engine.score(image_path, question.text))
        except Exception as err:
            _LOG.debug("SigLIP2Screen: call-time failure scoring atom %r: %s", question.atom_id, err, exc_info=True)
            raise PromptCraftError(
                "RUNTIME_VERIFIER_CALL_FAILED",
                f"SigLIP2 engine raised while scoring atom {question.atom_id!r}: {err}",
                hint="The engine constructed fine; the failure happened during the actual scoring "
                "call (bad image path, CUDA OOM mid-run, a shape mismatch, ...). This is distinct "
                "from SKIPPED -- the tier had a chance to run and blew up mid-question.",
                cause=err,
            ) from err
