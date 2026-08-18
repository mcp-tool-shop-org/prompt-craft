"""prompt-craft — typed depictable contracts, constrained synth, cross-family gate."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    """Installed distribution version. Fallback is the tree's declared 0.2.1."""
    try:
        return version("prompt-crafter")
    except PackageNotFoundError:
        return "0.2.1"
