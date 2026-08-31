"""Structured error shape for prompt-craft.

Ported from the mcp-tool-shop shipcheck error contract (Tier-1 shape: code / message /
hint / cause? / retryable?) and renamed. Every user-facing error carries a machine-readable,
namespaced ``code``, a human ``message``, and an actionable ``hint``. ``to_safe_text`` is the
end-user / LLM / MCP surface (no traceback); ``to_debug_text`` is gated behind ``--debug``.

Error-code namespaces (prefix -> CLI exit code):
    INPUT_   bad user input / missing args / invalid contract      -> exit 1
    CONFIG_  misconfiguration (missing key, bad threshold table)    -> exit 1
    CONTRACT_ contract resolution / relaxation violations           -> exit 1
    SYNTH_   synthesizer output defect (coverage, prose dump)       -> exit 2
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

The third override goes the other way. A receipt written by a NEWER build is
well formed, not a crash, so it is user input like its contract sibling
CONTRACT_SCHEMA_UNSUPPORTED -- not an IO_ runtime fault:

    IO_RECORD_SCHEMA_UNSUPPORTED  receipt schema_version is from the future -> exit 1

CORRECTED IN PLACE (F-a2de5ab2). Both tables above had drifted from the maps
they describe: SYNTH_ was missing from the namespace list, and the
IO_RECORD_SCHEMA_UNSUPPORTED override (F-4846c12e) was added to STABILITY.md
and to _EXIT_BY_CODE but not here -- so the front-door table in the file that
DEFINES the mapping still read "IO_ ... -> exit 2", with the correction living
only in a comment forty lines below. This block is the only override list a
reader of this file will find, so it is now parsed and compared against
_EXIT_BY_CODE / _EXIT_BY_PREFIX by tests/test_stability_surface.py: adding an
entry to either map without adding its row here goes red.
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
    # CORRECTED IN PLACE (F-4846c12e). STABILITY.md introduces this code and
    # CONTRACT_SCHEMA_UNSUPPORTED together, as the same idea applied to the two on-disk
    # formats -- and they did not get the same exit code. The IO_ prefix mapped a receipt
    # from the future to 2 ("prompt-craft crashed") while its contract sibling got 1 ("fix
    # your input"). A receipt that is perfectly well formed and merely written by a newer
    # build is user input, not a runtime fault, so it takes the same 1 the sibling takes.
    "IO_RECORD_SCHEMA_UNSUPPORTED": 1,
}

DEFAULT_HINTS: Final[dict[str, str]] = {
    "DEP_IMAGE_MISSING": "Install the GPU extra: pip install -e '.[image]' (torch + diffusers).",
    "DEP_SYNTH_MISSING": "Install the synth extra: pip install -e '.[synth]' (DSPy + an LM backend).",
    "STATE_COMPILE_NEEDS_GATE": "Call compile_synthesizer from Python with an EXTERNAL gate_metric. "
    "The CLI does not generate pixels. --seed pins the scaffold artifact.",
    "STATE_COMPILE_NOT_WIRED": "Use optimizer='gepa' or 'miprov2'. Unknown names refuse.",
    "STATE_COMPILE_EMPTY": "The optimizer returned nothing to pin. Check the runner.",
    "GATE_SAME_FAMILY": "The generator and the gate verifier are the same model family. "
    "Use a different-family verifier -- a model must never be its own gate.",
    "GATE_FAMILIES_NOT_A_LIST": "Pass a list of verifier family names. A bare string is iterated as characters and the guard cannot fire.",
    "GATE_CLIPSCORE_BANNED": "CLIPScore is banned as the gate metric (bag-of-concepts, blind to "
    "binding/counts). Use SigLIP2 (Tier-0), VQAScore (Tier-1), or DSG (Tier-2).",
    "GATE_CLOUD_SUBMIT": "Flux wrote the Cloud recipe graph. Submit it with pcraft recipe "
    "--image-name; it does not run Kontext locally.",
    "GATE_CONDITIONING_UNSUPPORTED": "SDXL applies ControlNet OpenPose, IP-Adapter, "
    "method=lora, and InstantID. method=reference is the Cloud Kontext stitch + left "
    "crop + fist-only Fill recipe (`pcraft recipe`). Flux refuses IP-Adapter, LoRA, "
    "and InstantID. InstantID and IP-Adapter cannot share one generate.",
    "GATE_CONDITIONING_REF_MISSING": "Pass a real image path for every pose_ref, identity plate, "
    "and inpaint_from. A missing plate is a refuse, not a plain text-to-image render.",
    "CONTRACT_RELAXATION": "A character contract may not drop or relax a faction-required atom, "
    "and may not rewrite inherited content (claim, check_type, spatial, enum, depends_on). "
    "Raise the severity, or add a new id -- never substitute an existing id's content.",
    "IO_GATE_INPUT": "Pass a readable image file. A missing path is not a failed atom. Exit 4.",
    "GATE_UNAVAILABLE": "Install the [image] extra (pip install -e '.[image]') so a verifier can score. Exit 4, not 2 -- this is not a failed atom.",
    "GATE_FAIL": "A required contract atom failed. Identity still gates nothing. Exit 2.",
    "PARTIAL_UNCONFIRMED": "At least one required atom was scored but the roll-up is UNCERTAIN. Human band. Exit 3.",
    "IO_RECORD_INVALID": "The receipt is JSON but does not match the AssetRecord schema. Re-bind, or pass --debug.",
    "IO_RECORD_SCHEMA_UNSUPPORTED": "This receipt was written by a NEWER prompt-craft than the "
    "one reading it. Upgrade prompt-craft to read it. Do NOT re-bind: the file is well formed, "
    "not corrupt, and re-binding would destroy a good receipt. Exit 1 (your input), not 2.",
    "CONFIG_THRESHOLDS_INVALID": "Each band needs high >= low and both in [0, 1]. Recalibrate or fix the table.",
    # F-09f30018: the version-disagreement refusal in orchestrate.run() used to reuse
    # CONFIG_THRESHOLDS_INVALID, which load_thresholds already raises for a structurally
    # malformed table. One covered, machine-parseable code then carried two unrelated meanings
    # -- "your table is broken" and "your table is fine but it is not the one you named" --
    # while the hint above described only the first. STABILITY.md tells callers to parse the
    # code, not the prose, so the two failures get two codes.
    "CONFIG_THRESHOLDS_VERSION_MISMATCH": "The table you named is not the table you passed. Pass "
    "the version of the table you are actually running (table.version), or leave "
    "config.thresholds_version unset to assert nothing.",
    "CONTRACT_CYCLIC_DEPENDS_ON": "Two or more atoms depend_on each other (or an atom depends_on "
    "itself), so no parent-first order exists and the gate cannot evaluate parents before "
    "children. Break the cycle in the contract's depends_on edges. Exit 1 (your input), not 2.",
    "INPUT_EMPTY_STORE": "Pass --contracts-dir at a tree that contains *.contract.json, or omit it to use the shipped sprite example.",
    "INPUT_IMAGE_NAME": "Pass --image-name as local.png=cloud-hash.png (repeatable).",
    "INPUT_CONTRACTS_DIR": "The path must be an existing directory.",
    "RUNTIME_UNEXPECTED": "An unclassified error escaped the command. Re-run with --debug to see "
    "the underlying traceback; this code is the backstop, not a diagnosis.",
    "RUNTIME_GENERATE_EXHAUSTED": "Every best-of-N generate() attempt failed before an image "
    "existed, so nothing was gated. The message names the last failure -- fix THAT code, not the "
    "seed. A failure that repeats on every attempt is not transient: check the generator's model "
    "load and its dependencies. Re-run with --debug for the underlying traceback.",
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
