"""Gate N images against ONE contract in one invocation, with ONE verifier construction.

F-8cfaf7ec. ``pcraft gate`` takes exactly one image, so gating a turnaround or a chapter's
plates is N processes -- and each process calls ``ImagePlugin.verifiers()`` fresh, and each
verifier caches its scorer on the INSTANCE, so the cache dies with the process and every image
pays a full load of clip-flant5-xxl plus SigLIP2 plus the Tier-2 localizer.

The library was already shaped for this and only the door was missing:
``harness.evaluate(dag, image_path, verifiers, thresholds, *, generator_family)`` takes an
ALREADY-CONSTRUCTED ``verifiers`` dict and a PER-CALL ``image_path``, so N images over one
verifier dict is the signature it already has. This module is that loop, plus the two things a
loop needs that a single call did not: a per-image containment rule, and an aggregation rule for
the exit code.

Four properties, each one a promise it would be easy to break.

ONE CONSTRUCTION, N IMAGES. The verifier dict is the caller's, built once and reused. That is
the whole point, and it is why this function does not accept a factory -- a factory is how "once"
quietly becomes "once per image" again.

BUT NOT ONE GUARD, N IMAGES. ``forbid_clipscore`` and ``assert_distinct_families`` run inside
``evaluate`` (F-461c4198, after the standalone ``pcraft gate`` path was found bypassing them), so
they run for EVERY image here because every image goes through ``evaluate``. Hoisting them out of
the loop is the obvious optimisation and it is forbidden: EXTERNAL_VERIFIER is a per-protected-
operation discipline, not a per-process one, and the cost is two set comparisons.

ONE BAD IMAGE IS ONE BAD ROW. ``preflight_image``'s ``IO_GATE_INPUT`` refusal is per image and
stays per image: an unreadable file is reported as its own result and the other N-1 keep their
verdicts. "The first bad file ends the report" is the exact failure the N-processes workaround
already has, and reproducing it inside one process would be no improvement.

THE 4-WAY EXIT CONTRACT IS NOT COLLAPSED. See ``BatchGateReport.exit_code``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ...errors import PromptCraftError, exit_code_for
from ..contract.compile_questions import QuestionDAG
from .exit_contract import error_from_transcript
from .harness import GateTranscript, evaluate
from .preflight import preflight_image
from .thresholds import ThresholdTable
from .verifier_iface import Verifier

COULD_NOT_RUN = 4
"""The exit code that means "could not run", named rather than spelled as a literal 4.

``errors.exit_code_for`` owns the mapping and this module compares against it in three places;
a bare 4 in each would be three chances to disagree with the one table that decides."""

_PRECEDENCE: tuple[int, ...] = (COULD_NOT_RUN, 2, 3, 0)
"""Worst-first, and deliberately NOT the numeric order of the codes.

``4`` outranks ``2`` because the alternative is the thing the finding forbids by name: a batch
holding one image that could not be read and one that genuinely failed would report ``2``, which
is "the gate ran and refused" -- a could-not-run image laundered into a content verdict. Ranking
could-not-run first is what makes "a could-not-run image never becomes a ``2``" a property of the
ordering rather than a comment. ``2`` outranks ``3`` for the same reason it does on one image: a
confirmed required failure is a stronger statement than an unconfirmed one.

``1`` is absent on purpose. A contract-level refusal is not one image's outcome (see
``_BATCH_WIDE_PREFIXES``); it refuses the batch before any result exists."""

_BATCH_WIDE_PREFIXES = ("CONTRACT_", "CONFIG_", "INPUT_")
_BATCH_WIDE_CODES = frozenset(
    {"GATE_SAME_FAMILY", "GATE_FAMILIES_NOT_A_LIST", "GATE_CLIPSCORE_BANNED"}
)
"""Refusals that are properties of the CONTRACT, the TABLE or the VERIFIER SET -- never of one
image -- and therefore propagate instead of becoming a row.

The test is what the refusal is ABOUT, not where it was raised. A cyclic ``depends_on``, a
malformed threshold table and a same-family gate are identical for image 1 and image 500, so
containing them per image would print one authoring defect N times and still refuse. Everything
else is contained: an unreadable file, a verifier that raised on these particular pixels, an
extra that is missing. Those can differ between two images in one batch, and the whole reason
this door exists is that one of them must not void the rest."""


class BatchImageResult(BaseModel):
    """One image's outcome: a transcript, or the coded refusal that stopped this image alone.

    ``code`` is ``""`` when the exit contract answered PASS -- the same absent-is-empty-string
    convention the receipt already uses for ``thresholds_fingerprint`` and ``band_key``, so a
    JSON consumer never meets a null. ``transcript`` is the one nullable field, because "the
    gate ran and this is what it said" and "the gate never ran on this file" are genuinely two
    different shapes and flattening them would be the merge this module exists to prevent.
    """

    model_config = ConfigDict(extra="forbid")
    image_path: str
    transcript: GateTranscript | None = None
    code: str = ""
    message: str = ""
    hint: str = ""
    exit_code: int = 0

    @property
    def gated(self) -> bool:
        """The gate actually ran on this image and produced a transcript."""
        return self.transcript is not None

    @property
    def passed(self) -> bool:
        return self.transcript is not None and not self.code

    @property
    def could_not_run(self) -> bool:
        """Keyed on the covered exit code rather than on a second list of codes.

        ``4`` is what "could not run" MEANS in this product (STABILITY.md), so asking the
        mapping is asking the definition; enumerating ``IO_GATE_INPUT`` / ``GATE_UNAVAILABLE``
        here would be a copy of it, free to drift the moment a third code joins them.
        """
        return self.exit_code == COULD_NOT_RUN


class BatchGateReport(BaseModel):
    """What one contract decided about N images. A report, not a verdict.

    The per-image results are the answer; ``exit_code()`` is a summary of them for a caller who
    can only read one number, and it is lossy on purpose. Nothing here re-decides anything: every
    ``code`` came from ``exit_contract.error_from_transcript``, the same function ``pcraft gate``
    calls, so a one-image batch says exactly what the single-image gate says.
    """

    model_config = ConfigDict(extra="forbid")
    contract_id: str
    thresholds_version: str
    results: list[BatchImageResult] = Field(default_factory=list)

    def passed(self) -> list[BatchImageResult]:
        return [r for r in self.results if r.passed]

    def gated(self) -> list[BatchImageResult]:
        return [r for r in self.results if r.gated]

    def unrunnable(self) -> list[BatchImageResult]:
        return [r for r in self.results if r.could_not_run]

    def any_unrunnable(self) -> bool:
        return any(r.could_not_run for r in self.results)

    def all_unrunnable(self) -> bool:
        """Every image could not run -- the batch as a whole did not run.

        Published beside ``any_unrunnable`` so the distinction the exit code cannot carry is
        answerable MECHANICALLY rather than by reading the message prose.
        """
        return bool(self.results) and all(r.could_not_run for r in self.results)

    def exit_code(self) -> int:
        """The batch's own aggregation rule, stated rather than inherited.

            0  every image was gated and every one passed.
            4  at least one image could not run. ``4`` keeps meaning could-not-run, and
               ``all_unrunnable()`` says whether that was the whole batch or part of it.
            2  no image was blocked from running, and at least one was gated and FAILED.
            3  no image was blocked and none failed, and at least one is unconfirmed.

        The precedence is ``_PRECEDENCE`` and it is not the numeric order -- see that constant
        for why ``4`` has to outrank ``2``. A contract-level refusal never reaches here; it
        raises out of ``evaluate_batch`` before a report exists, at its own code's exit 1.
        """
        seen = {r.exit_code for r in self.results}
        for code in _PRECEDENCE:
            if code in seen:
                return code
        return 0

    def summary(self) -> str:
        """One line an operator can read. ASCII, no width assumptions: this is a library return
        value and the surface that prints it owns the wrapping (``pcraft.errors``'s convention)."""
        n = len(self.results)
        parts = [f"{len(self.passed())} of {n} passed"]
        for label, rows in (
            ("failed", [r for r in self.results if r.code == "GATE_FAIL"]),
            ("unconfirmed", [r for r in self.results if exit_code_for(r.code) == 3 and r.code]),
            ("could not run", self.unrunnable()),
        ):
            if rows:
                parts.append(f"{len(rows)} {label}")
        return ", ".join(parts) + "."


def evaluate_batch(
    dag: QuestionDAG,
    image_paths: Sequence[str | Path],
    verifiers: dict[int, Verifier],
    thresholds: ThresholdTable,
    *,
    generator_family: str,
) -> BatchGateReport:
    """Gate every image in ``image_paths`` against ``dag``, reusing ``verifiers`` throughout.

    The argument order mirrors ``harness.evaluate`` exactly, with the single ``image_path``
    widened to a sequence -- because that IS the change: the finding's own reading is that "N
    images over one verifier dict is the signature it already has".

    Raises rather than returns for a defect that belongs to the batch as a whole (see
    ``_BATCH_WIDE_CODES``); every other coded refusal becomes one row and the loop continues.
    """
    paths = [str(p) for p in image_paths]
    if not paths:
        raise PromptCraftError(
            "INPUT_GATE_BATCH_EMPTY",
            "no images were passed to the batch gate, so nothing was decided",
        )

    results = [
        _gate_one(dag, path, verifiers, thresholds, generator_family) for path in paths
    ]
    return BatchGateReport(
        contract_id=dag.contract_id,
        thresholds_version=thresholds.version,
        results=results,
    )


def _gate_one(
    dag: QuestionDAG,
    path: str,
    verifiers: dict[int, Verifier],
    thresholds: ThresholdTable,
    generator_family: str,
) -> BatchImageResult:
    """One image, contained. ``preflight`` and ``evaluate`` are called exactly as the
    single-image path calls them, so this image's answer is the answer it would have got alone."""
    try:
        preflight_image(path)
        transcript = evaluate(
            dag, path, verifiers, thresholds, generator_family=generator_family
        )
    except PromptCraftError as err:
        if err.code in _BATCH_WIDE_CODES or err.code.startswith(_BATCH_WIDE_PREFIXES):
            raise
        return _refused(path, err)
    refusal = error_from_transcript(transcript)
    if refusal is None:
        return BatchImageResult(image_path=path, transcript=transcript)
    return BatchImageResult(
        image_path=path, transcript=transcript, code=refusal.code, message=refusal.message,
        hint=refusal.hint, exit_code=refusal.exit_code,
    )


def _refused(path: str, err: PromptCraftError) -> BatchImageResult:
    return BatchImageResult(
        image_path=path, code=err.code, message=err.message, hint=err.hint,
        exit_code=err.exit_code,
    )


def error_from_batch(report: BatchGateReport) -> PromptCraftError | None:
    """None means every image passed. Anything else carries the WORST image's own code.

    Deliberately no new code and no new exit-code override: a batch is the existing exit
    contract applied N times, so inventing ``GATE_BATCH_*`` would give a scripted caller a second
    vocabulary for facts it can already parse -- and would have to be added to the covered
    mapping to say anything the existing codes do not.

    The message is the batch's, because the aggregate's job is to say how many and which. A
    caller that wants the single-image sentence verbatim has it on the result row: ``code``,
    ``message`` and ``hint`` there are the very fields ``pcraft gate`` prints today, which is
    what makes a one-image batch answer exactly what the one-image gate answers.
    """
    if not report.results:
        return None
    code = report.exit_code()
    if code == 0:
        return None
    worst = next(r for r in report.results if r.exit_code == code)
    n = len(report.results)
    named = ", ".join(r.image_path for r in report.results if r.exit_code == code)
    if code == COULD_NOT_RUN and report.all_unrunnable():
        message = (
            f"none of the {n} image(s) could be gated, so the batch as a whole did not run "
            f"({worst.code}: {worst.message})"
        )
        hint = (
            "This is not a batch of failures; it is a batch that never ran. "
            "The report names every image and its own code."
        )
    elif code == COULD_NOT_RUN:
        message = (
            f"{len(report.unrunnable())} of {n} image(s) could not be gated ({named}); the "
            f"other {n - len(report.unrunnable())} produced verdicts and keep them"
        )
        hint = (
            "Could-not-check is not checked-clean, so this batch is reported as could-not-run "
            "rather than merged onto a content failure. Fix the images the message names and "
            "re-run; the images that did produce a verdict are in the report already."
        )
    else:
        message = (
            f"{len([r for r in report.results if r.exit_code == code])} of {n} image(s) "
            f"answered {worst.code} ({named}): {worst.message}"
        )
        hint = worst.hint
    return PromptCraftError(worst.code, message, hint)


__all__ = [
    "COULD_NOT_RUN",
    "BatchGateReport",
    "BatchImageResult",
    "error_from_batch",
    "evaluate_batch",
]
