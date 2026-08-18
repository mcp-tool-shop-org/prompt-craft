"""prompt-craft — typed depictable contracts, constrained synth, cross-family gate."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


_FALLBACK_VERSION = "0.3.0"
"""Must equal pyproject's ``[project].version``.

Pinned by ``test_the_version_fallback_matches_pyproject``: this literal is only reachable
when the distribution is not installed (running straight from a checkout), which is exactly
when nobody notices it has gone stale. It sat at ``0.2.1`` through the 0.3.0 bump, so an
uninstalled checkout would have reported the previous release's number from ``pcraft
--version`` and ``pcraft doctor`` -- a version claim that disagrees with the tree it is
running from.
"""


def package_version() -> str:
    """Installed distribution version, falling back to the tree's declared version."""
    try:
        return version("prompt-crafter")
    except PackageNotFoundError:
        return _FALLBACK_VERSION
