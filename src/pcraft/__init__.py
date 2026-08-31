"""prompt-craft -- typed depictable contracts, constrained synth, cross-family gate."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_FALLBACK_VERSION = "1.0.1"
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


def version_coherence() -> str | None:
    """A warning when installed metadata disagrees with the tree it is imported from.

    ``package_version()`` above covers exactly one of the two ways this can go wrong: no
    distribution installed at all. The other -- a distribution that IS installed but whose
    ``dist-info`` is stale -- returns the wrong number as fact, with no flag, no warning
    and no nonzero exit. That is not hypothetical: this checkout was measured serving
    ``0.2.1`` from ``pcraft --version`` and ``pcraft doctor`` against a ``1.0.0`` tree,
    because an editable install's ``dist-info`` is not regenerated when pyproject's version
    changes. ``verify.py``'s notes record the same class landing twice before.

    The only guard that existed lived behind ``verify.py --installed``, a maintainer-only
    opt-in dev leg that no user runs. This is the same check on the user's side of the door.

    Returns ``None`` when the two agree, and ``None`` when nothing is installed -- with no
    second opinion there is nothing to disagree with, and that path is already pinned by
    ``test_the_version_fallback_matches_pyproject``. ``package_version()`` is deliberately
    left alone: it is a covered import path (STABILITY.md) and "returns the distribution
    version" stays true. This is a separate signal, not a rewrite of that promise.
    """
    try:
        installed = version("prompt-crafter")
    except PackageNotFoundError:
        return None
    if installed == _FALLBACK_VERSION:
        return None
    return (
        f"installed prompt-crafter metadata says {installed}, but this source tree declares "
        f"{_FALLBACK_VERSION}; the dist-info is stale, so the version above is not the code "
        "you are running (reinstall: pip install -e . --no-deps)"
    )
