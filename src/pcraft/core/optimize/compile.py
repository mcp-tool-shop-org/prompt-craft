"""OFFLINE optimize: compile the synthesizer against the gate pass-rate (GEPA / MIPROv2).

Folklore this kills: "always evolve the prompt live" and "bigger model = better prompt." Gains come
from the offline *search loop*, not from per-asset scale. The budget rule is **scale at
optimize-time, small at run-time**: the 600B (Ollama-Cloud) is the proposer/mutator inside this
offline compile; the compiled, pinned prompt then runs on a cheap local model per asset.

GEPA reads the gate's natural-language per-atom failure text and reflectively evolves the prompt
against a Pareto frontier. This module is OFFLINE ONLY. It is never imported by the per-asset
loop. The default runner is ``dspy.GEPA`` (the ``[synth]`` extra). Tests inject a runner so the
suite stays GPU-free. The metric is always EXTERNAL -- the optimizer never scores its own text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ...errors import PromptCraftError
from ..contract.schema import ResolvedContract
from .artifact import CompiledProgram, pin

GateMetric = Callable[[ResolvedContract, str], float]


class OptimizedPrompt(BaseModel):
    """What an optimizer returns. instruction + demos, never a self-score."""

    model_config = ConfigDict(extra="forbid")
    instruction: str
    demos: list[dict] = Field(default_factory=list)
    metric_calls: int = 0


class Optimizer(Protocol):
    def compile(
        self,
        *,
        trainset: list[ResolvedContract],
        gate_metric: GateMetric,
        base_instruction: str,
    ) -> OptimizedPrompt: ...


def compile_synthesizer(
    trainset: list[ResolvedContract],
    gate_metric: GateMetric,
    *,
    out_path: str | Path,
    program_id: str,
    base_instruction: str,
    optimizer: str = "gepa",
    runner: Optimizer | None = None,
) -> CompiledProgram:
    """Run an offline optimize loop and pin the result.

    ``gate_metric(contract, prompt) -> [0,1]`` is the EXTERNAL gate pass-rate -- the optimizer
    never scores its own output. A missing ``[synth]`` extra is ``DEP_SYNTH_MISSING`` unless
    a ``runner`` is injected (the test door).
    """
    if not trainset:
        raise PromptCraftError(
            "INPUT_EMPTY_STORE",
            "offline compile needs at least one resolved contract in the trainset",
            hint="Pass the contracts you will generate. An empty trainset cannot evolve a prompt.",
        )
    name = (optimizer or "gepa").strip().lower()
    if name not in {"gepa", "miprov2"}:
        raise PromptCraftError(
            "STATE_COMPILE_NOT_WIRED",
            f"unknown offline optimizer {optimizer!r}",
            hint="Use gepa (default) or miprov2.",
        )
    worker = runner if runner is not None else _default_runner(name)
    result = worker.compile(
        trainset=trainset, gate_metric=gate_metric, base_instruction=base_instruction
    )
    if not result.instruction.strip():
        raise PromptCraftError(
            "STATE_COMPILE_EMPTY",
            "the optimizer returned an empty instruction",
            hint="The compile ran and produced nothing to pin. Check the runner / dspy.GEPA log.",
        )
    source_hash = _source_hash(trainset, name)
    program = CompiledProgram(
        program_id=program_id,
        version=_next_version(
            name,
            instruction=result.instruction,
            demos=result.demos,
            source_hash=source_hash,
        ),
        instruction=result.instruction,
        demos=list(result.demos),
        generated_by=name,
        source_hash=source_hash,
    )
    pin(program, out_path)
    return program


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


def _next_version(
    optimizer: str, *, instruction: str, demos: list[dict], source_hash: str
) -> str:
    """A version that actually distinguishes one compile from the next (F-4184d73f).

    This returned ``f"v1-{optimizer}"`` -- a pure function of the optimizer NAME, with no
    counter, no lookup of prior pins, nothing that varies run to run. Since
    ``CompiledProgram.artifact_id`` is ``f"{program_id}@{version}"``, the ordinary
    iterate-and-recompile workflow (change the trainset or the base instruction, re-run
    gepa) produced two artifacts with different ``instruction``/``demos``/``source_hash``
    and the SAME artifact id. That id is what every asset receipt carries as the claim
    "this run is replayable bit-for-bit", so the one property this module exists to provide
    was the one it did not.

    The suffix is a CONTENT fingerprint, not a clock and not a counter. Two compiles that
    produce byte-identical output land on the same id -- which is correct, and is what makes
    replay checkable -- while any change to what was pinned changes the id. No wall-clock or
    filesystem state enters, so a compile is reproducible offline and the property is
    testable without freezing time.

    ``source_hash`` alone would not do it: it covers the trainset and the optimizer name but
    not ``base_instruction``, so a re-compile that changed only the instruction would still
    collide. Hashing the pinned content closes both cases at once.
    """
    h = hashlib.sha256()
    h.update(optimizer.encode("utf-8"))
    h.update(b"\0")
    h.update(source_hash.encode("utf-8"))
    h.update(b"\0")
    h.update(instruction.encode("utf-8"))
    h.update(b"\0")
    # Sort keys so an equal-content demo dict cannot change the id through key order.
    h.update(json.dumps(list(demos), sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return f"v1-{optimizer}-{h.hexdigest()[:12]}"


def _source_hash(trainset: list[ResolvedContract], optimizer: str) -> str:
    h = hashlib.sha256()
    h.update(optimizer.encode("utf-8"))
    for contract in trainset:
        h.update(contract.id.encode("utf-8"))
        for atom in contract.must_have:
            h.update(atom.id.encode("utf-8"))
            h.update(atom.claim.encode("utf-8"))
    return h.hexdigest()[:16]


def _default_runner(optimizer: str) -> Optimizer:
    try:
        import dspy  # noqa: F401
    except Exception as err:
        raise PromptCraftError(
            "DEP_SYNTH_MISSING",
            "offline compile needs DSPy + an LM backend",
            hint="Install the [synth] extra, or inject a runner in tests.",
        ) from err
    return _DspyGepaRunner(optimizer)


class _DspyGepaRunner:
    """Live ``dspy.GEPA`` / ``dspy.MIPROv2`` wrapper. Not imported on the per-asset path."""

    def __init__(self, optimizer: str) -> None:
        self.optimizer = optimizer

    def compile(
        self,
        *,
        trainset: list[ResolvedContract],
        gate_metric: GateMetric,
        base_instruction: str,
    ) -> OptimizedPrompt:
        import dspy

        from ..synth.signature import _HAS_DSPY, ContractToPrompt

        if not _HAS_DSPY:
            raise PromptCraftError(
                "DEP_SYNTH_MISSING",
                "ContractToPrompt needs DSPy",
            )
        metric_calls = 0

        class _Program(dspy.Module):
            def __init__(self) -> None:
                super().__init__()
                self.predict = dspy.Predict(ContractToPrompt)

            def forward(self, resolved_contract: str, encoder_rules: str):
                return self.predict(
                    resolved_contract=resolved_contract, encoder_rules=encoder_rules
                )

        examples = []
        for contract in trainset:
            ex = dspy.Example(
                resolved_contract=contract.model_dump_json(),
                encoder_rules=base_instruction,
            ).with_inputs("resolved_contract", "encoder_rules")
            ex.resolved = contract
            examples.append(ex)

        def metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
            nonlocal metric_calls
            metric_calls += 1
            prompt = getattr(pred, "prompt", "") or ""
            contract = getattr(gold, "resolved", None)
            if contract is None:
                return 0.0
            score = float(gate_metric(contract, prompt))
            if score < 0.0 or score > 1.0:
                return 0.0
            return score

        if self.optimizer == "miprov2":
            if not hasattr(dspy, "MIPROv2"):
                raise PromptCraftError(
                    "STATE_COMPILE_NOT_WIRED",
                    "this DSPy build has no dspy.MIPROv2",
                )
            opt = dspy.MIPROv2(metric=metric, auto="light")
        else:
            if not hasattr(dspy, "GEPA"):
                raise PromptCraftError(
                    "STATE_COMPILE_NOT_WIRED",
                    "this DSPy build has no dspy.GEPA",
                    hint="Upgrade DSPy, or inject a runner. GEPA is offline-only.",
                )
            opt = dspy.GEPA(metric=metric, auto="light", reflection_lm=_require_lm(dspy))
        compiled = opt.compile(student=_Program(), trainset=examples)
        instruction = _extract_instruction(compiled, fallback=base_instruction)
        demos = _extract_demos(compiled)
        return OptimizedPrompt(instruction=instruction, demos=demos, metric_calls=metric_calls)


def _require_lm(dspy_module):
    """DSPy 3.3 GEPA asserts a reflection LM. Use the configured one. No silent default."""
    lm = getattr(getattr(dspy_module, "settings", None), "lm", None)
    if lm is None:
        raise PromptCraftError(
            "DEP_SYNTH_MISSING",
            "dspy.GEPA needs a configured LM (dspy.configure(lm=...))",
            hint="Point DSPy at a real LM before compile_synthesizer. "
            "A local Ollama model counts. Do not invent a pixel metric.",
        )
    return lm


def _extract_instruction(program, *, fallback: str) -> str:
    predict = getattr(program, "predict", program)
    for attr in ("extended_signature", "signature"):
        sig = getattr(predict, attr, None)
        if sig is None:
            continue
        inst = getattr(sig, "instructions", None)
        if inst:
            return str(inst)
    return fallback


def _extract_demos(program) -> list[dict]:
    predict = getattr(program, "predict", program)
    raw = getattr(predict, "demos", None) or []
    out: list[dict] = []
    for demo in raw:
        if hasattr(demo, "toDict"):
            out.append(demo.toDict())
        elif isinstance(demo, dict):
            out.append(demo)
        else:
            out.append({"repr": repr(demo)})
    return out
