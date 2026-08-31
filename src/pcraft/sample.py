"""Load the generic sprite example and run the loop GPU-free.

Shared by the CLI (`pcraft demo`) and the test suite, so the end-to-end sample is defined once.
Wires the deterministic TemplateSynthesizer + StubGenerator + two different-family
ScriptedVerifiers (Tier-0 + Tier-1, via ``testing.passing_verifiers``), so the whole
synth->generate->gate->retry->bind loop runs with no GPU and no network -- and so the tier
census it produces reflects tiers actually executed, not tiers Tier-1 merely fell forward to."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

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


IMAGE_EXTRA_MODULES: Final[tuple[str, ...]] = (
    "torch",
    "diffusers",
    "transformers",
    "accelerate",
    "PIL",
    "numpy",
)
"""Import names for every distribution in pyproject's ``[image]`` extra. ONE list.

There used to be two. ``image_extra_present()`` -- the door that gates ``bind --no-mock``
-- checked ``torch/diffusers/PIL``, while ``doctor``'s ``_extra_status("image", ...)``
checked those plus ``transformers``, and the extra itself declares six distributions. So
the two answers to "is [image] installed" disagreed, and the one actually guarding the live
pipeline was the weaker one: an env with torch + diffusers + Pillow but no transformers
walked past the refusal and died inside the VQA-family verifiers, which downgraded an
actionable ``DEP_IMAGE_MISSING`` (whose hint names the exact install command) to the
generic ``RUNTIME_UNEXPECTED`` backstop. Both map to exit 2, so the exit-code contract
hid the difference and only the CODE -- the part STABILITY.md says is parseable --
degraded.

Not read from installed metadata at runtime, deliberately. ``Requires-Dist`` comes from the
same dist-info that this repo has now twice been caught serving stale (F-4d031e47: a 0.2.1
dist-info against a 1.0.0 tree), so deriving the door from it would make a safety check
depend on the exact artifact that is known to go stale -- and would put a metadata parse on
every ``bind`` invocation. The correspondence to pyproject is pinned by
``tests/test_packaging.py::test_the_image_extra_module_list_matches_pyproject`` instead,
which fails loudly when the extra gains or loses a distribution.
"""


def missing_image_modules() -> tuple[str, ...]:
    """Which of the [image] extra's modules cannot be imported. Empty means complete."""
    import importlib.util

    return tuple(m for m in IMAGE_EXTRA_MODULES if importlib.util.find_spec(m) is None)


def image_extra_present() -> bool:
    """True when the [image] extra can import. Used by bind --no-mock."""
    return not missing_image_modules()


class _AnnouncingGenerator:
    """Narrate each generate() to a callback, then delegate. Progress without a framework.

    ``run_live_loop`` is minutes of silence on real hardware (F-710c9599), and the incremental
    information an operator needs -- which attempt is running, at which seed -- exists only
    inside ``orchestrate.run``, which is domain-agnostic and has no opinion about output. Rather
    than teach the loop about progress, this wraps the one object the loop calls once per
    attempt. The loop reads exactly two things off a generator: ``family`` (once, for
    ``assert_distinct_families``) and ``generate(...)`` (once per attempt), so forwarding those
    is the whole surface.

    The receipt is untouched by design: ``generator_id`` and ``generator_family`` are stamped
    from the ``GenerationResult`` the REAL generator returns, so provenance still names the
    model that made the pixels and never this wrapper.

    A raised generate() is announced before it is re-raised. The loop classifies that failure
    itself (TRANSIENT retries, SEMANTIC escalates) and records its own Attempt row; swallowing
    it here would be a defect, and staying silent about it would put the one attempt an operator
    most wants to see back inside the silence this class exists to end.
    """

    def __init__(self, inner, on_attempt: Callable[..., None]) -> None:
        self._inner = inner
        self._on_attempt = on_attempt
        self._n = 0
        self.generator_id = inner.generator_id
        self.family = inner.family

    def generate(self, prompt: str, negative_prompt: str, conditioning: dict, seed: int):
        self._n += 1
        n = self._n
        self._on_attempt(n, seed, "generating...")
        try:
            result = self._inner.generate(prompt, negative_prompt, conditioning, seed)
        except Exception as err:  # announced, then re-raised untouched -- not a blind except
            self._on_attempt(n, seed, "generate FAILED: ", type(err).__name__)
            raise
        self._on_attempt(n, seed, "generated ", result.image_path)
        return result


def run_live_loop(
    *,
    records_dir: str | Path = "records",
    contract_id: str | None = None,
    contracts_dirs: list[Path] | None = None,
    thresholds: Path | None = None,
    on_attempt: Callable[..., None] | None = None,
) -> OrchestrationResult:
    """Real plugin generator + verifiers. Not the stub. Needs [image].

    The per-asset synthesizer stays TemplateSynthesizer. GEPA is offline.

    ``on_attempt(attempt, seed, state, detail)`` is called around every generate() so a caller
    can report progress during a run that is otherwise silent for minutes; the CLI passes one
    and renders to stderr. Omitting it changes nothing about the run.
    """
    from .domains.image import ImagePlugin

    # `image_extra_present()` stays the single gate: it is the seam the suite monkeypatches
    # to exercise both sides of this door GPU-free, so the decision must not be re-derived
    # here. The missing-module list is only used to make the refusal actionable.
    if not image_extra_present():
        from .errors import PromptCraftError

        missing = missing_image_modules() or IMAGE_EXTRA_MODULES
        raise PromptCraftError(
            "DEP_IMAGE_MISSING",
            f"real bind needs the [image] extra; missing: {', '.join(missing)}",
            # The registry form LEADS; the checkout form is the parenthetical (F-3c6d9f4f).
            # This is the product's principal "how do I go live" unblock, and it used to name
            # only `pip install -e '.[image]'` -- which needs a buildable project in the cwd.
            # README.md makes `pip install prompt-crafter` (PyPI, non-editable, no checkout
            # anywhere) the primary documented install, and the npm launcher installs no
            # checkout either, so for the majority install the hinted command failed inside pip
            # with "neither setup.py nor pyproject.toml found" -- a second and less legible wall
            # than the one the user started at, reached by following the CLI's own advice.
            # npm/bin/pcraft.mjs already tells users the registry form; this is the layer that
            # was undoing it. The quotes are load-bearing and stay in the string: unquoted
            # brackets are glob characters in zsh, the default shell on macOS.
            hint="pip install 'prompt-crafter[image]' (from a source checkout: "
            "pip install -e '.[image]'). Use --mock for the GPU-free scaffold.",
        )
    _store, resolved, table, compiled = load_workspace(
        contracts_dirs=contracts_dirs, thresholds=thresholds, contract_id=contract_id
    )
    plugin = ImagePlugin()
    gen = plugin.generator()
    gen.out_dir = Path(records_dir) / "_image"  # set on the REAL generator, before wrapping
    if on_attempt is not None:
        gen = _AnnouncingGenerator(gen, on_attempt)
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
