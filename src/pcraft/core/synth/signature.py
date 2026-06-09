"""The DSPy Signature (the real, compiled synthesizer) + a deterministic template fallback.

The production synthesizer is a *compiled DSPy module* (a pinned artifact, never a hand-written
mega-prompt). DSPy is an optional ``[synth]`` dependency; when it is installed, ``ContractToPrompt``
is the Signature the optimizer compiles against, and ``DSPySynthesizer`` runs the pinned program on
an Ollama-Cloud (600B compile-time) or local-8B (run-time) ``/v1`` backend.

``TemplateSynthesizer`` is the GPU-free, network-free fallback: deterministic, every token traces to
a depictable atom by construction. It is what lets the whole synth->generate->gate->bind loop run in
the core test suite with no model at all."""

from __future__ import annotations

from ..contract.schema import ResolvedContract
from ..optimize.artifact import CompiledProgram
from .synthesizer_iface import SynthResult
from .visual_inventory import RENDER_BOILERPLATE, build_inventory

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
except Exception:  # pragma: no cover - exercised only without the extra
    _HAS_DSPY = False


class TemplateSynthesizer:
    """Deterministic fallback synthesizer. Implements the ``Synthesizer`` protocol."""

    synthesizer_id = "template.v1"

    def __init__(self, compiled: CompiledProgram | None = None) -> None:
        self.compiled = compiled
        if compiled is not None:
            self.synthesizer_id = f"template.v1+{compiled.program_id}@{compiled.version}"

    def synthesize(self, resolved: ResolvedContract, encoder_rules: str) -> SynthResult:
        inventory = build_inventory(resolved)
        depictable = sorted((r for r in inventory if r.depictable), key=lambda r: r.front_load_rank)
        atom_coverage = {r.atom_id: r.token for r in depictable}
        prompt = ", ".join([r.token for r in depictable] + RENDER_BOILERPLATE)
        # must_not feeds a SOFT negative prior only — satisfaction is confirmed by the gate on pixels.
        negative_prompt = ", ".join(mn.claim for mn in resolved.must_not)
        return SynthResult(
            prompt=prompt,
            negative_prompt=negative_prompt,
            atom_coverage=atom_coverage,
            visual_inventory=inventory,
            backend="template",
            degraded=False,
        )
