"""Load the generic sprite example and run the loop GPU-free.

Shared by the CLI (`pcraft demo`) and the test suite, so the end-to-end sample is defined once.
Wires the deterministic TemplateSynthesizer + StubGenerator + two different-family
ScriptedVerifiers (Tier-0 + Tier-1, via ``testing.passing_verifiers``), so the whole
synth->generate->gate->retry->bind loop runs with no GPU and no network -- and so the tier
census it produces reflects tiers actually executed, not tiers Tier-1 merely fell forward to."""

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
from .testing import StubGenerator, passing_verifiers


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
    mutate_contract: Callable[[ResolvedContract], None] | None = None,
) -> OrchestrationResult:
    """Run the example contract through the full loop with deterministic stubs.

    ``verifier_scores`` (atom_id -> score) scripts the gate; the default passes every atom and binds.
    Pass e.g. ``{"face": 0.1}`` to drive the faceless-hero failure into the repair ladder.

    ``mutate_contract`` runs against the resolved contract before compilation, so a caller can state
    a premise instead of inheriting one from the example's policy. The example's ``must_not`` atoms
    are ``optional`` (absence-verification is unmeasured on this stack), so a test about blocking
    behaviour raises the severity itself rather than depending on a setting that can change."""
    _store, resolved, thresholds, compiled = load_sprite_example()
    if mutate_contract is not None:
        mutate_contract(resolved)
    synth = TemplateSynthesizer(compiled)
    gen = generator or StubGenerator(out_dir=Path(records_dir) / "_stub_images")
    # Both branches register Tier-0 AND Tier-1. The scripted branch used to build a lone
    # Tier-1 verifier, which -- now that a missing wanted tier is SKIPPED rather than
    # falling forward (F-175c3b3e) and the census gates the verdict (F-834dd470) -- made
    # every scripted scenario report "1 of 2 required tiers executed" and escalate. That
    # would have been the mock lying about coverage, not the loop misbehaving, so the mock
    # is what changes. `scores` is forwarded to both tiers, so a scripted atom scores the
    # same whichever tier owns it.
    verifiers = passing_verifiers(scores=verifier_scores)
    config = LoopConfig(
        encoder_rules=_encoder_rules(),
        thresholds_version=thresholds.version,
        records_dir=str(records_dir),
    )
    return orchestrate.run(resolved, synth, gen, verifiers, thresholds, config=config)
