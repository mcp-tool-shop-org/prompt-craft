"""Structured error shape for prompt-craft.

Ported from the mcp-tool-shop shipcheck error contract (Tier-1 shape: code / message /
hint / cause? / retryable?) and renamed. Every user-facing error carries a machine-readable,
namespaced ``code``, a human ``message``, and an actionable ``hint``. ``to_safe_text`` is the
end-user / LLM / MCP surface (no traceback); ``to_debug_text`` is gated behind ``--debug``.

Error-code namespaces (prefix → CLI exit code):
    INPUT_   bad user input / missing args / invalid contract      -> exit 1
    CONFIG_  misconfiguration (missing key, bad threshold table)    -> exit 1
    CONTRACT_ contract resolution / relaxation violations           -> exit 1
    GATE_    gate / verifier discipline violations                  -> exit 2
    DEP_     missing optional dependency ([image]/[synth] extra)    -> exit 2
    IO_      filesystem read/write failure                          -> exit 2
    RUNTIME_ unexpected runtime crash                               -> exit 2
    STATE_   illegal state transition in the loop                  -> exit 2
    PARTIAL_ partial success (some atoms unverified)                -> exit 3
"""

from __future__ import annotations

import traceback
from typing import Final

# prefix -> CLI exit code (Tier-2). 0 success, 1 user error, 2 runtime error, 3 partial.
_EXIT_BY_PREFIX: Final[dict[str, int]] = {
    "INPUT_": 1,
    "CONFIG_": 1,
    "CONTRACT_": 1,
    "SYNTH_": 2,
    "GATE_": 2,
    "DEP_": 2,
    "IO_": 2,
    "RUNTIME_": 2,
    "STATE_": 2,
    "PARTIAL_": 3,
}

DEFAULT_HINTS: Final[dict[str, str]] = {
    "DEP_IMAGE_MISSING": "Install the GPU extra: pip install -e '.[image]' (torch + diffusers).",
    "DEP_SYNTH_MISSING": "Install the synth extra: pip install -e '.[synth]' (DSPy + an LM backend).",
    "GATE_SAME_FAMILY": "The generator and the gate verifier are the same model family. "
    "Use a different-family verifier — a model must never be its own gate.",
    "GATE_CLIPSCORE_BANNED": "CLIPScore is banned as the gate metric (bag-of-concepts, blind to "
    "binding/counts). Use SigLIP2 (Tier-0), VQAScore (Tier-1), or DSG (Tier-2).",
    "CONTRACT_RELAXATION": "A character contract may not drop or relax a faction-required atom. "
    "Raise the severity/threshold, or override the atom — never weaken inherited requirements.",
}


def exit_code_for(code: str) -> int:
    """Map an error code to its CLI exit code via its namespace prefix (default 2)."""
    for prefix, exit_code in _EXIT_BY_PREFIX.items():
        if code.startswith(prefix):
            return exit_code
    return 2


class PromptCraftError(Exception):
    """The one structured error type. Rename of shipcheck's ProductError."""

    def __init__(
        self,
        code: str,
        message: str,
        hint: str | None = None,
        *,
        cause: BaseException | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.hint = hint or DEFAULT_HINTS.get(code, "")
        self.cause = cause
        self.retryable = retryable
        super().__init__(f"[{code}] {message}")

    @property
    def exit_code(self) -> int:
        return exit_code_for(self.code)

    def to_safe_text(self) -> str:
        """No stack trace. For end users / LLM / MCP output."""
        lines = [f"error[{self.code}]: {self.message}"]
        if self.hint:
            lines.append(f"  hint: {self.hint}")
        if self.retryable:
            lines.append("  (retryable)")
        return "\n".join(lines)

    def to_debug_text(self) -> str:
        """Includes the underlying traceback. Only behind --debug."""
        text = self.to_safe_text()
        if self.cause is not None:
            tb = "".join(traceback.format_exception(type(self.cause), self.cause, self.cause.__traceback__))
            text += f"\n  caused by:\n{tb}"
        return text


def wrap_error(err: BaseException, code: str, hint: str | None = None) -> PromptCraftError:
    """Wrap any exception into the structured type, passing through if already one."""
    if isinstance(err, PromptCraftError):
        return err
    return PromptCraftError(code, str(err) or err.__class__.__name__, hint, cause=err)
