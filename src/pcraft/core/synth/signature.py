"""The DSPy Signature (the real, compiled synthesizer) + a deterministic template fallback.

The production synthesizer is a *compiled DSPy module* (a pinned artifact, never a hand-written
mega-prompt). DSPy is an optional ``[synth]`` dependency; when it is installed, ``ContractToPrompt``
is the Signature the optimizer compiles against, and ``DSPySynthesizer`` runs the pinned program on
an Ollama-Cloud (600B compile-time) or local-8B (run-time) ``/v1`` backend.

``TemplateSynthesizer`` is the GPU-free, network-free fallback: deterministic, every token traces to
a depictable atom by construction. It is what lets the whole synth->generate->gate->bind loop run in
the core test suite with no model at all."""

from __future__ import annotations

from collections.abc import Callable

from ...errors import PromptCraftError
from ..contract.schema import ResolvedContract
from ..optimize.artifact import CompiledProgram
from .synthesizer_iface import SynthResult
from .visual_inventory import assert_tokens_trace, build_inventory, parse_render_boilerplate

try:  # the real Signature is only defined when the [synth] extra is installed
    import dspy

    class ContractToPrompt(dspy.Signature):
        """Convert a resolved contract's depictable atoms into a single diffusion prompt.

        Front-load by salience. Emit ONLY tokens that trace to an atom; identity (face/insignia) is
        bound by conditioning, not described in tokens; render/style boilerplate is appended last."""

        resolved_contract: str = dspy.InputField(desc="the resolved contract as JSON")
        encoder_rules: str = dspy.InputField(desc="domain encoder-craft rules (generated)")
        visual_inventory: str = dspy.OutputField(desc="per-atom {depictable, front_load_rank, token}")
        prompt: str = dspy.OutputField(desc="the diffusion prompt; every token traces to an atom")
        negative_prompt: str = dspy.OutputField(desc="soft prior only; must_not is gate-enforced")
        atom_coverage: str = dspy.OutputField(desc="JSON {atom_id: phrase} for every required atom")

    _HAS_DSPY = True
except Exception:  # noqa: BLE001  # pragma: no cover - exercised only without the extra
    _HAS_DSPY = False


class TemplateSynthesizer:
    """Deterministic fallback synthesizer. Implements the ``Synthesizer`` protocol."""

    synthesizer_id = "template.v1"

    def __init__(self, compiled: CompiledProgram | None = None) -> None:
        self.compiled = compiled
        if compiled is not None:
            self.synthesizer_id = f"template.v1+{compiled.program_id}@{compiled.version}"

    def synthesize(
        self,
        resolved: ResolvedContract,
        encoder_rules: str,
        *,
        boost_ids: list[str] | None = None,
    ) -> SynthResult:
        inventory = build_inventory(resolved, boost_ids=boost_ids)
        depictable = sorted((r for r in inventory if r.depictable), key=lambda r: r.front_load_rank)
        atom_coverage = {r.atom_id: r.token for r in depictable}
        # [!] `encoder_rules` IS READ NOW (F-c6b06c2f). It was accepted and ignored -- the exact
        # seam plugin.py's DomainPlugin.encoder_rules_path() exists to supply, per domain --
        # while the trailing tokens came from a module-level constant that is sprite/image
        # phrasing. Rules that declare no boilerplate block (every shipped rules file, and the
        # "" this method's own tests pass) still get RENDER_BOILERPLATE, byte for byte.
        boilerplate = parse_render_boilerplate(encoder_rules)
        prompt = ", ".join([r.token for r in depictable] + boilerplate)
        # must_not feeds a SOFT negative prior only -- satisfaction is confirmed by the gate on pixels.
        negative_prompt = ", ".join(mn.claim for mn in resolved.must_not)
        return SynthResult(
            prompt=prompt,
            negative_prompt=negative_prompt,
            atom_coverage=atom_coverage,
            visual_inventory=inventory,
            backend="template",
            degraded=False,
        )


class DSPySynthesizer:
    """Run a pinned GEPA artifact. The compile is offline; this is the cheap per-asset runner.

    Needs the ``[synth]`` extra (or an injected ``predictor``). Missing DSPy is
    ``DEP_SYNTH_MISSING``, never a silent TemplateSynthesizer fallback.
    """

    synthesizer_id = "dspy.v1"

    def __init__(
        self,
        compiled: CompiledProgram,
        *,
        predictor: Callable[..., SynthResult] | None = None,
    ) -> None:
        if compiled is None:
            raise PromptCraftError(
                "STATE_COMPILE_EMPTY",
                "DSPySynthesizer needs a pinned CompiledProgram",
                hint="Run pcraft compile (offline GEPA) or pass --seed for the scaffold artifact.",
            )
        self.compiled = compiled
        self._predictor = predictor
        self.synthesizer_id = f"dspy.v1+{compiled.artifact_id}"

    def synthesize(
        self,
        resolved: ResolvedContract,
        encoder_rules: str,
        *,
        boost_ids: list[str] | None = None,
    ) -> SynthResult:
        rules = encoder_rules or self.compiled.instruction
        if boost_ids:
            rules = rules + "\nfront-load failed atoms: " + ", ".join(boost_ids)
        if self._predictor is not None:
            result = self._predictor(resolved, rules, self.compiled)
            # [!] THE SAME GUARD THE REAL PATH RUNS (F-4d4b5b17). This branch used to return
            # the predictor's result untouched, so assert_tokens_trace -- called by _run_dspy
            # below, and the ONLY guard that inspects the prompt string itself -- was the one
            # guard the injected path skipped. MEASURED: a predictor returning
            # 'epic cinematic masterpiece, trending on artstation, 8k, hyperdetailed' (the
            # exact prose-dump shape the guard exists to catch) plus a FABRICATED
            # atom_coverage self-reporting full coverage of atoms the prompt never mentions
            # was accepted with zero refusal. The sibling assert_coverage gives false
            # confidence here: it only checks that the self-reported phrases are non-empty,
            # never that they relate to the prompt, so a predictor satisfies it while ignoring
            # the prompt entirely.
            #
            # The inventory is RECOMPUTED from the resolved contract rather than read off
            # result.visual_inventory, for the same reason the coverage is not trusted: both
            # are predictor-controlled and were measured diverging from the actual prompt text.
            # Ground truth for "does this token trace to an atom" is the contract.
            #
            # predictor= is test infrastructure today, but this module's own docstring names an
            # Ollama-Cloud / local-8B /v1 backend as the intended real integration point for
            # this seam -- so "test-only" is a temporary property, not a structural one. The
            # seam stays; the OUTPUT is guarded. Costs no GPU and no network.
            assert_tokens_trace(result.prompt, build_inventory(resolved))
            return result.model_copy(
                update={"backend": f"dspy:{self.compiled.artifact_id}", "degraded": False}
            )
        if not _HAS_DSPY:
            raise PromptCraftError(
                "DEP_SYNTH_MISSING",
                "DSPySynthesizer needs DSPy + an LM backend",
                hint="Install the [synth] extra, or inject a predictor in tests. "
                "Do not silently fall back to TemplateSynthesizer.",
            )
        return self._run_dspy(resolved, rules)

    def _run_dspy(self, resolved: ResolvedContract, encoder_rules: str) -> SynthResult:
        import json

        predict = dspy.Predict(ContractToPrompt)
        pred = predict(
            resolved_contract=resolved.model_dump_json(),
            encoder_rules=encoder_rules,
        )
        coverage_raw = getattr(pred, "atom_coverage", "") or "{}"
        try:
            coverage = json.loads(coverage_raw) if isinstance(coverage_raw, str) else dict(coverage_raw)
        except (TypeError, ValueError):
            coverage = {}
        inventory = build_inventory(resolved)
        prompt = str(getattr(pred, "prompt", "") or "")
        negative = str(getattr(pred, "negative_prompt", "") or "")
        if not prompt.strip():
            # [!] ITS OWN CODE (F-97765221). This raised SYNTH_COVERAGE_MISSING, whose only
            # other producer -- assert_.assert_coverage -- always embeds the uncovered atoms.
            # STABILITY.md says a code will not have its meaning changed under a minor and
            # tells callers to "parse the code, not the prose", so the code IS the contract a
            # caller keys on: one that reads SYNTH_COVERAGE_MISSING and looks for the atom
            # list every other producer gives it found none when this branch fired. Two
            # structurally different failures ("the synthesizer covered N atoms short" vs "the
            # backend returned nothing at all") get two codes, exactly as F-09f30018 split
            # CONFIG_THRESHOLDS_VERSION_MISMATCH out of CONFIG_THRESHOLDS_INVALID.
            #
            # Additive and minor-safe: a NEW code, same SYNTH_ namespace, same exit 2. The
            # hint is inline rather than in DEFAULT_HINTS so this refusal resolves advice at
            # the raise site, where the surrounding context (a pinned program, an offline
            # recompile) is known.
            required = resolved.required_atoms()
            raise PromptCraftError(
                "SYNTH_EMPTY_PROMPT",
                f"DSPy returned an empty prompt for {resolved.id!r} "
                f"({len(required)} required atom(s) expected coverage: "
                f"{[a.id for a in required]})",
                hint="The pinned program produced no tokens at all -- this is the backend "
                "returning nothing, not a partial synthesis. Check the LM backend is "
                "reachable and re-run the offline compile; do not re-pin an artifact that "
                "generates empty prompts.",
            )
        assert_tokens_trace(prompt, inventory)
        return SynthResult(
            prompt=prompt,
            negative_prompt=negative,
            atom_coverage={str(k): str(v) for k, v in coverage.items()},
            visual_inventory=inventory,
            backend=f"dspy:{self.compiled.artifact_id}",
            degraded=False,
        )
