"""Tier-2 verifier: DSG per-atom DAG localization.

Cho et al. 2024 (arXiv:2310.18235). A failed/borderline Tier-1 atom is
expanded into entity / attribute / relation yes-no probes. The answerer
scores each probe. A missing entity (score below the VQA low band) makes
dependents N/A. The returned score is the mean of the probes that ran.

The template decomposer is the default QG. Inject ``qg`` to swap it.
``qg_model`` is the label on that slot — it is read, not stored-and-ignored.

The default answerer is still the Tier-1 VQAScore model. That sharing is
surfaced on ``shares_model_with``. Family stays ``dsg-qg`` (the QG step is
what this tier adds). Lazy + graceful: missing extra -> None / SKIPPED.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ....core.contract.compile_questions import Question
from ....errors import PromptCraftError
from .dsg_expand import DSGExpansion, SubProbe, template_expand
from .vqascore_verifier import DEFAULT_MODEL_ID as _VQA_TIER1_DEFAULT_MODEL_ID

_LOG = logging.getLogger(__name__)

# Same number as the shipped VQA low band. Below this the entity is absent.
ENTITY_ABSENT = 0.40
QG_TEMPLATE = "template.dsg.v1"


class DSGVerifier:
    family = "dsg-qg"
    tier = 2
    verifier_id = "dsg.localizer.v1"
    version = "dsg-v2"

    def __init__(
        self,
        answerer_model: str = _VQA_TIER1_DEFAULT_MODEL_ID,
        qg_model: str = QG_TEMPLATE,
        qg: Callable[[Question], list[SubProbe]] | None = None,
    ):
        self.answerer_model = answerer_model
        self.qg_model = qg_model
        self._qg = qg
        self._answerer = None
        self._unavailable = False
        self.last_expansion: DSGExpansion | None = None
        self.shares_model_with: str | None = (
            "vqascore.clip-flant5.v1" if answerer_model == _VQA_TIER1_DEFAULT_MODEL_ID else None
        )

    def expand(self, question: Question) -> DSGExpansion:
        """Run the QG slot. Template by default; injected ``qg`` wins."""
        if self._qg is not None:
            probes = list(self._qg(question))
            if not probes:
                probes = template_expand(question).probes
            return DSGExpansion(atom_id=question.atom_id, source=f"qg:{self.qg_model}", probes=probes)
        return template_expand(question)

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
                _LOG.debug(
                    "DSGVerifier: answerer construction failed for model=%r: %s",
                    self.answerer_model,
                    err,
                    exc_info=True,
                )
                raise PromptCraftError(
                    "RUNTIME_VERIFIER_INIT_FAILED",
                    f"DSG answerer failed to construct (model={self.answerer_model!r}): {err}",
                    hint="This is not a missing t2v_metrics extra -- construction itself failed "
                    "(bad model id, corrupted checkpoint, CUDA OOM at load, ...). Check the cause.",
                    cause=err,
                ) from err
        return self._answerer

    def _ask(self, answerer, image_path: str, text: str, atom_id: str) -> float:
        try:
            result = answerer(images=[image_path], texts=[text])
            return float(result[0][0])
        except Exception as err:
            _LOG.debug("DSGVerifier: call-time failure scoring atom %r: %s", atom_id, err, exc_info=True)
            raise PromptCraftError(
                "RUNTIME_VERIFIER_CALL_FAILED",
                f"DSG answerer raised while scoring atom {atom_id!r}: {err}",
                hint="The answerer constructed fine; the failure happened during the actual scoring "
                "call (bad image path, CUDA OOM mid-run, ...). This is distinct from SKIPPED -- the "
                "tier had a chance to run and blew up mid-question.",
                cause=err,
            ) from err

    def score(self, image_path: str, question: Question) -> float | None:
        answerer = self._get_answerer()
        if answerer is None:
            return None
        expansion = self.expand(question)
        # F-f5cc9257: this call was unguarded, in deliberate contrast to ``_ask`` directly above,
        # which classifies everything the answerer can throw. A cyclic injected expansion raised a
        # raw RecursionError straight through score(), and harness._safe_score's bare
        # ``except Exception`` turned it into a SKIPPED verdict blaming this instrument for the
        # caller's malformed expansion. Guarded the way harness.evaluate guards its own sibling
        # walker (harness.py:159-169): a coded refusal passes through, and the two non-PromptCraft
        # exception types a recursive walk can produce become that same code rather than a crash.
        try:
            ordered = expansion.topological()
        except PromptCraftError:
            raise
        except (ValueError, RecursionError) as err:
            raise PromptCraftError(
                "CONTRACT_CYCLIC_DEPENDS_ON",
                f"DSG expansion for atom {question.atom_id!r} has no parent-first probe order: {err}",
                cause=err,
            ) from err
        scores: dict[str, float | None] = {}
        for probe in ordered:
            parent = probe.depends_on
            if parent is not None:
                parent_score = scores.get(parent)
                if parent_score is None or parent_score < ENTITY_ABSENT:
                    scores[probe.id] = None
                    continue
            scores[probe.id] = self._ask(answerer, image_path, probe.text, question.atom_id)
        expansion.scores = scores
        self.last_expansion = expansion
        ran = [s for s in scores.values() if s is not None]
        if not ran:
            return None
        return sum(ran) / len(ran)
