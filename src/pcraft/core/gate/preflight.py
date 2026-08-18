"""Refuse a gate run before any verifier is consulted, if the input cannot be seen.

A missing path, a directory, and an unreadable file are the same class of
defect: the gate has no image. They are not UNCERTAIN and they are not
"extras not installed". The check lives here so the CLI and the loop share
it, and so a ScriptedVerifier test can still pass a fake path to
``evaluate`` without tripping I/O.
"""

from __future__ import annotations

from pathlib import Path

from ...errors import PromptCraftError


def preflight_image(path: str | Path) -> Path:
    """Raise IO_GATE_INPUT if `path` is not a readable file. Never creates anything."""
    p = Path(path)
    if not p.exists():
        raise PromptCraftError(
            "IO_GATE_INPUT",
            f"image does not exist: {p}",
            hint="Pass a readable image file. A missing path is exit 4, not a failed atom.",
        )
    if not p.is_file():
        raise PromptCraftError(
            "IO_GATE_INPUT",
            f"image path is not a file: {p}",
            hint="Pass a file, not a directory.",
        )
    try:
        with p.open("rb"):
            pass
    except OSError as err:
        raise PromptCraftError(
            "IO_GATE_INPUT",
            f"image is unreadable: {p}",
            cause=err,
            hint="Check permissions. An unreadable file is not an UNCERTAIN score.",
        ) from err
    return p
