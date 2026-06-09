"""OFFLINE optimize: compile the synthesizer against the gate pass-rate (GEPA / MIPROv2).

Folklore this kills: "always evolve the prompt live" and "bigger model = better prompt." Gains come
from the offline *search loop*, not from per-asset scale. The budget rule is **scale at
optimize-time, small at run-time**: the 600B (Ollama-Cloud) is the proposer/mutator inside this
offline compile; the compiled, pinned prompt then runs on a cheap local model per asset.

GEPA reads the gate's natural-language per-atom failure text (the DSG verdicts) and reflectively
evolves the prompt against a Pareto frontier — ">10% over MIPROv2, +6% avg up to +20% over GRPO,"
with up to 35x fewer rollouts (each rollout is a full diffusion gen + gate, so this is
budget-justified). This module is OFFLINE ONLY and requires the ``[synth]`` extra; it is never on a
per-asset hot path."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ...errors import PromptCraftError
from ..contract.schema import ResolvedContract
from .artifact import CompiledProgram, pin


def compile_synthesizer(
    trainset: list[ResolvedContract],
    gate_metric: Callable[[ResolvedContract, str], float],
    *,
    out_path: str | Path,
    program_id: str,
    base_instruction: str,
    optimizer: str = "gepa",
) -> CompiledProgram:
    """Run an offline optimize loop and pin the result. Requires the ``[synth]`` extra.

    ``gate_metric(contract, prompt) -> [0,1]`` is the EXTERNAL gate pass-rate — the optimizer never
    scores its own output. The compiled artifact is written to ``out_path`` (pinned, do-not-edit)."""
    try:
        import dspy  # noqa: F401
    except Exception as err:  # pragma: no cover
        raise PromptCraftError(
            "DEP_SYNTH_MISSING",
            "offline compile needs DSPy + an LM backend",
        ) from err

    # Real implementation: build the DSPy program from ContractToPrompt, wrap gate_metric as the
    # DSPy metric, run dspy.GEPA / dspy.MIPROv2 over the trainset, extract the optimized
    # instruction + demos, and pin them. Left as the offline-compile entry point: it is GPU-heavy
    # and runs out-of-band, gated by the Director, not in the core test suite.
    raise PromptCraftError(
        "STATE_COMPILE_NOT_WIRED",
        f"offline {optimizer} compile is not wired in the scaffold",
        hint="Wire dspy.GEPA against the external gate metric, then pin via optimize.artifact.pin(). "
        "This runs OFFLINE (watchdog up), gated by the Director — never on a per-asset path.",
    )


def write_seed_artifact(out_path: str | Path, program_id: str, instruction: str) -> CompiledProgram:
    """Pin a scaffold SEED artifact (generated_by='scaffold-seed') so the loop has a pinned program
    before a real GEPA compile exists. Replaced by ``compile_synthesizer`` output later."""
    seed = CompiledProgram(
        program_id=program_id,
        version="v1-scaffold-seed",
        instruction=instruction,
        demos=[],
        generated_by="scaffold-seed",
    )
    pin(seed, out_path)
    return seed
