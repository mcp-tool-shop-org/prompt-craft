"""Load the generic sprite example and run the loop GPU-free.

Shared by the CLI (`pcraft demo`) and the test suite, so the end-to-end sample is defined once.
Wires the deterministic TemplateSynthesizer + StubGenerator + a different-family ScriptedVerifier,
so the whole synth->generate->gate->retry->bind loop runs with no GPU and no network."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .core.contract.compile_questions import Question
from .core.contract.loader import ContractStore
from .core.contract.schema import ResolvedContract
from .core.gate.thresholds import ThresholdTable, load_thresholds
from .core.loop import orchestrate
from .core.loop.orchestrate import LoopConfig, OrchestrationResult
from .core.optimize.artifact import CompiledProgram, load_pinned
from .core.synth.signature import TemplateSynthesizer
from .domains.image import COMPILED_ARTIFACT, RULES_PATH
from .domains.image.subdomains.sprite import CONTRACTS_DIR, EXAMPLE_CHARACTER_ID, THRESHOLDS_PATH
from .testing import ScriptedVerifier, StubGenerator, passing_verifiers


def load_sprite_example() -> tuple[ContractStore, ResolvedContract, ThresholdTable, CompiledProgram]:
    store = ContractStore([CONTRACTS_DIR])
    resolved = store.resolve(EXAMPLE_CHARACTER_ID)
    thresholds = load_thresholds(THRESHOLDS_PATH)
    compiled = load_pinned(COMPILED_ARTIFACT)
    return store, resolved, thresholds, compiled


def _encoder_rules() -> str:
    return RULES_PATH.read_text(encoding="utf-8") if RULES_PATH.exists() else ""


def run_mock_loop(
    *,
    records_dir: str | Path = "records",
    verifier_scores: dict[str, float] | Callable[[Question], float] | None = None,
    generator=None,
) -> OrchestrationResult:
    """Run the example contract through the full loop with deterministic stubs.

    ``verifier_scores`` (atom_id -> score) scripts the gate; the default passes every atom and binds.
    Pass e.g. ``{"face": 0.1}`` to drive the faceless-hero failure into the repair ladder."""
    _store, resolved, thresholds, compiled = load_sprite_example()
    synth = TemplateSynthesizer(compiled)
    gen = generator or StubGenerator(out_dir=Path(records_dir) / "_stub_images")
    if verifier_scores is None:
        verifiers = passing_verifiers()
    else:
        v = ScriptedVerifier(verifier_scores)
        verifiers = {v.tier: v}
    config = LoopConfig(
        encoder_rules=_encoder_rules(),
        thresholds_version=thresholds.version,
        records_dir=str(records_dir),
    )
    return orchestrate.run(resolved, synth, gen, verifiers, thresholds, config=config)
