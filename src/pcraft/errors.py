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
    PARTIAL_ ran, required atom unconfirmed (human band)            -> exit 3

Per-code overrides (win over the prefix). Practice, not a paper: Nagios
0 OK / 1 WARNING / 2 CRITICAL / 3 UNKNOWN never overloads CRITICAL with
"could not run." We already spent 3 on PARTIAL_ (the WARNING analog).
Could-not-run therefore sits at 4, not 2:

    GATE_UNAVAILABLE  no required atom produced a score              -> exit 4
    IO_GATE_INPUT     path missing / not a file / unreadable         -> exit 4
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

# Could-not-run is not GATE_FAIL. The codes already differ; only the number
# a CI branch reads was collapsing them onto 2.
_EXIT_BY_CODE: Final[dict[str, int]] = {
    "GATE_UNAVAILABLE": 4,
    "IO_GATE_INPUT": 4,
}

DEFAULT_HINTS: Final[dict[str, str]] = {
    "DEP_IMAGE_MISSING": "Install the GPU extra: pip install -e '.[image]' (torch + diffusers).",
    "DEP_SYNTH_MISSING": "Install the synth extra: pip install -e '.[synth]' (DSPy + an LM backend).",
    "GATE_SAME_FAMILY": "The generator and the gate verifier are the same model family. "
    "Use a different-family verifier — a model must never be its own gate.",
    "GATE_FAMILIES_NOT_A_LIST": "Pass a list of verifier family names. A bare string is iterated as characters and the guard cannot fire.",
    "GATE_CLIPSCORE_BANNED": "CLIPScore is banned as the gate metric (bag-of-concepts, blind to "
    "binding/counts). Use SigLIP2 (Tier-0), VQAScore (Tier-1), or DSG (Tier-2).",
    "CONTRACT_RELAXATION": "A character contract may not drop or relax a faction-required atom, "
    "and may not rewrite inherited content (claim, check_type, spatial, enum, depends_on). "
    "Raise the severity, or add a new id — never substitute an existing id's content.",
    "IO_GATE_INPUT": "Pass a readable image file. A missing path is not a failed atom. Exit 4.",
    "GATE_UNAVAILABLE": "Install the [image] extra (pip install -e '.[image]') so a verifier can score. Exit 4, not 2 — this is not a failed atom.",
    "GATE_FAIL": "A required contract atom failed. Identity still gates nothing. Exit 2.",
    "PARTIAL_UNCONFIRMED": "At least one required atom was scored but the roll-up is UNCERTAIN. Human band. Exit 3.",
    "IO_RECORD_INVALID": "The receipt is JSON but does not match the AssetRecord schema. Re-bind, or pass --debug.",
    "INPUT_EMPTY_STORE": "Pass --contracts-dir at a tree that contains *.contract.json, or omit it to use the shipped sprite example.",
    "INPUT_CONTRACTS_DIR": "The path must be an existing directory.",
    "RUNTIME_UNEXPECTED": "An unclassified error escaped the command. Re-run with --debug to see "
    "the underlying traceback; this code is the backstop, not a diagnosis.",
}


def exit_code_for(code: str) -> int:
    """Map an error code to its CLI exit code. Per-code overrides win; then prefix."""
    if code in _EXIT_BY_CODE:
        return _EXIT_BY_CODE[code]
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
