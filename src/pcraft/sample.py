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


def load_workspace(
    *,
    contracts_dirs: list[Path] | None = None,
    thresholds: Path | None = None,
    contract_id: str | None = None,
) -> tuple[ContractStore, ResolvedContract, ThresholdTable, CompiledProgram]:
    """Load a contract store. Defaults to the shipped sprite example.

    F-CLI-FEAT-001: --contracts-dir / --thresholds are the public door.
    An empty tree is INPUT_EMPTY_STORE, not a silent ashen-reaver fallback.
    """
    store = load_store(contracts_dirs)
    resolved = store.resolve(contract_id or EXAMPLE_CHARACTER_ID)
    table = load_thresholds(thresholds or THRESHOLDS_PATH)
    compiled = load_pinned(COMPILED_ARTIFACT)
    return store, resolved, table, compiled


def load_store(contracts_dirs: list[Path] | None = None) -> ContractStore:
    """Index *.contract.json trees. Empty is INPUT_EMPTY_STORE."""
    from .errors import PromptCraftError

    roots = [Path(r) for r in (contracts_dirs or [CONTRACTS_DIR])]
    if not roots:
        roots = [CONTRACTS_DIR]
    for root in roots:
        if not root.is_dir():
            raise PromptCraftError(
                "INPUT_CONTRACTS_DIR",
                f"contracts dir {str(root)!r} is not a directory",
                hint="Pass --contracts-dir at a folder that contains *.contract.json files.",
            )
    store = ContractStore(roots)
    if not store.ids():
        raise PromptCraftError(
            "INPUT_EMPTY_STORE",
            "no *.contract.json files in the given --contracts-dir",
            hint="The shipped sprite tree is the default. A custom dir must contain contracts.",
        )
    return store


def load_sprite_example(
    contract_id: str | None = None,
) -> tuple[ContractStore, ResolvedContract, ThresholdTable, CompiledProgram]:
    return load_workspace(contract_id=contract_id)


def _encoder_rules() -> str:
    return RULES_PATH.read_text(encoding="utf-8") if RULES_PATH.exists() else ""


def run_mock_loop(
    *,
    records_dir: str | Path = "records",
    contract_id: str | None = None,
    contracts_dirs: list[Path] | None = None,
    thresholds: Path | None = None,
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
    # Unpack into `table`, not back over `thresholds`: that parameter is the caller's
    # optional PATH to a threshold file, and rebinding it to the loaded ThresholdTable made
    # one name mean two types. Runtime was fine; the annotation was not, and it read as a
    # bug to anyone tracing the argument. `run_live_loop` below already spells it this way.
    _store, resolved, table, compiled = load_workspace(
        contracts_dirs=contracts_dirs, thresholds=thresholds, contract_id=contract_id
    )
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
        thresholds_version=table.version,
        records_dir=str(records_dir),
    )
    return orchestrate.run(resolved, synth, gen, verifiers, table, config=config)


def image_extra_present() -> bool:
    """True when the [image] extra can import. Used by bind --no-mock."""
    import importlib.util

    return all(importlib.util.find_spec(name) is not None for name in ("torch", "diffusers", "PIL"))


def run_live_loop(
    *,
    records_dir: str | Path = "records",
    contract_id: str | None = None,
    contracts_dirs: list[Path] | None = None,
    thresholds: Path | None = None,
) -> OrchestrationResult:
    """Real plugin generator + verifiers. Not the stub. Needs [image].

    The per-asset synthesizer stays TemplateSynthesizer. GEPA is offline.
    """
    from .domains.image import ImagePlugin

    if not image_extra_present():
        from .errors import PromptCraftError

        raise PromptCraftError(
            "DEP_IMAGE_MISSING",
            "real bind needs the [image] extra (torch + diffusers + Pillow)",
            hint="pip install -e '.[image]'. Use --mock for the GPU-free scaffold.",
        )
    _store, resolved, table, compiled = load_workspace(
        contracts_dirs=contracts_dirs, thresholds=thresholds, contract_id=contract_id
    )
    plugin = ImagePlugin()
    gen = plugin.generator()
    gen.out_dir = Path(records_dir) / "_image"
    config = LoopConfig(
        encoder_rules=_encoder_rules(),
        thresholds_version=table.version,
        records_dir=str(records_dir),
    )
    return orchestrate.run(
        resolved,
        TemplateSynthesizer(compiled),
        gen,
        plugin.verifiers(),
        table,
        config=config,
    )
