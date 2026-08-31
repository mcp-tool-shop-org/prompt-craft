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
from .region import full_frame_note
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
        # F-2c77d698. What the most recent score owes an atom whose declared region it did not
        # honour, or None. Written beside last_expansion, cleared in the same place and for the
        # same reason: a note left over from the previous atom describes the wrong contract.
        self.last_scope_note: str | None = None
        self.shares_model_with: str | None = (
            "vqascore.clip-flant5.v1" if answerer_model == _VQA_TIER1_DEFAULT_MODEL_ID else None
        )

    def expansion_summary(self) -> list[dict]:
        """The most recent expansion as flat rows: probe id, kind, and its score or None for N/A.

        F-65fe58d5. ``score`` has always parked the full entity/attribute/relation trail on
        ``last_expansion`` -- and a grep of the worktree found the only readers anywhere were this
        verifier's own tests. That is the shape F-64b4f422 named on ``Tier0Router.last_delegate``:
        a field that looks live, with tests asserting the field rather than the behaviour.

        PARITY NOTE (stated, because the remedies differ and the difference matters). The router's
        fix needed no new plumbing: ``verifier_id`` is a field the harness ALREADY reads and it was
        answering the question wrongly, so deriving it from the recorded delegate put the right
        answer on the transcript by itself. There is no equivalent field here.
        ``core.gate.harness.AtomVerdict`` is ``extra='forbid'`` with no detail/evidence member, and
        its ``reason`` is composed harness-side, so carrying a probe-level localization to the
        transcript is a core/gate change, not this domain's. Smuggling it through ``verifier_id``
        instead would break the ``"<band>.<instrument>.<version>"`` convention wave 6 wrote down in
        ``palette_verifier`` and would put a per-atom string into the receipt's ``verifier_ids``
        set. So this is the reader plus the rendered line, sitting on the instrument, waiting for
        the one field on the other side of the boundary.
        """
        expansion = self.last_expansion
        if expansion is None:
            return []
        scores = expansion.scores or {}
        return [
            {"id": probe.id, "kind": probe.kind, "score": scores.get(probe.id)}
            for probe in expansion.probes
        ]

    def localization_detail(self) -> str | None:
        """Which named probe failed or went N/A -- the thing a DSG mean cannot say.

        The reader ``expansion_summary`` needs so it is not stranded in turn, and the same service
        ``per_view`` already performs for ``IdentitySubGate``'s reason string. N/A is spelled out
        rather than shown as a number, because it is not a low score: it is the answer "the entity
        this probe depends on was absent, so the question did not apply".
        """
        rows = self.expansion_summary()
        if not rows:
            return None
        parts = [
            f"{row['id']}({row['kind']}) "
            + ("N/A" if row["score"] is None else f"{row['score']:.2f}")
            for row in rows
        ]
        body = f"{len(rows)} probe(s): " + ", ".join(parts)
        # F-2c77d698. This tier's whole job is LOCALIZATION, which makes it the most misleading
        # place to leave a declared region unmentioned: "which probe failed" reads as an answer to
        # "where", and the probes all ran on the whole frame. The note LEADS for that reason. It is
        # carried on the instrument rather than taken as an argument because this method's
        # signature is read by name from harness._detail_for and is already published no-argument.
        if self.last_scope_note:
            return f"{self.last_scope_note}; {body}"
        return body

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
        self.last_scope_note = None
        answerer = self._get_answerer()
        if answerer is None:
            return None
        # F-2c77d698: recorded before the probes run, so a refusal mid-expansion still leaves the
        # honest statement of what window this tier was working over.
        self.last_scope_note = full_frame_note(question, self.verifier_id)
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
