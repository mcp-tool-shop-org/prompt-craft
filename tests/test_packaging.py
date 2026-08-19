"""The wheel collision was four force-include entries of trees hatch already ships."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_wheel_does_not_force_include_trees_already_in_packages():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    wheel = data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get(
        "wheel", {}
    )
    assert "force-include" not in wheel
    packages = wheel.get("packages") or []
    assert "src/pcraft" in packages


def test_version_is_one_or_later_and_the_public_surface_agrees():
    """The version is 1.x, the README may not drift from it, and STABILITY.md must exist.

    ⚑ REPLACES `test_version_is_pre_one_and_the_readme_agrees`, which asserted the major was
    still `0` and said promoting "needs an evidence-backed decision, not a test edit." That is
    exactly what happened, so this is the edit the old test was holding the door for — not a
    deletion of an inconvenient assertion.

    The decision, in one line: the pre-1.0 ruling was *"a generate that ran is not a stability
    claim,"* which argues from **capability** — and capability is the category that does not
    block a stable interface. It gets better in minors. The real blockers were three markers
    that read as compatibility checks and were never compared: an unversioned receipt format
    whose reader was fail-closed in both directions, a `$schema` label that accepted any
    string, and a `thresholds_version` that was stamped into every receipt and asserted by
    nothing. All three are closed and pinned in `tests/test_stability_surface.py`.

    So the invariant flips rather than disappears. What is load-bearing now:

    1. **1.0 does not silently regress.** Dropping back to 0.x would retract a published
       stability promise, and that needs the same deliberation the promotion did.
    2. **The README cannot drift from the version.** Unchanged, and it is this repo's own
       defect one level up: a front door advertising a version the package does not carry.
    3. **The promise exists.** `1.0.0` without `STABILITY.md` is a number, not a commitment —
       the document is what names the covered surface and, just as importantly, the excluded
       one.
    """
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert int(version.split(".")[0]) >= 1, (
        f"version {version} regresses below 1.0.0; that retracts a published promise"
    )
    readme = Path("README.md").read_text(encoding="utf-8")
    assert f"v{version}" in readme, f"README does not state v{version}"

    stability = Path("STABILITY.md")
    assert stability.is_file(), "1.0.0 without STABILITY.md is a number, not a promise"
    assert "Development Status :: 5" in Path("pyproject.toml").read_text(encoding="utf-8"), (
        "the stable classifier and the stable version ship together or neither is honest"
    )


def test_ci_runs_the_declared_python_floor():
    """requires-python >=3.11 was metadata only. The 3.11 CI leg is the proof."""
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["requires-python"] == ">=3.11"
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"3.11"' in ci
    assert '"3.13"' in ci


def test_installed_package_ships_the_py_typed_marker():
    """A typed-contracts package that installs without py.typed is a packaging lie.

    PEP 561: type checkers only treat the install as typed when this marker is
    next to the package __init__. Hatch already ships every file under
    packages=["src/pcraft"]; the marker must exist so that path is not empty.
    """
    import pcraft

    marker = Path(pcraft.__file__).resolve().parent / "py.typed"
    assert marker.is_file(), f"missing py.typed next to {pcraft.__file__}"


def test_the_version_fallback_matches_pyproject():
    """The uninstalled-checkout fallback may not drift from the declared version.

    ``package_version()`` prefers installed distribution metadata, so this literal is only
    reached when the package is NOT installed -- a checkout run with PYTHONPATH=src. That is
    precisely the path nobody exercises before a release, and it sat at 0.2.1 through the
    0.3.0 bump: `pcraft --version` and `pcraft doctor` would have reported the previous
    release's number while running the new tree. A version that disagrees with its own source
    is this repo's own defect class wearing a different hat.
    """
    from pcraft import _FALLBACK_VERSION

    declared = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert declared == _FALLBACK_VERSION, (
        f"pcraft._FALLBACK_VERSION is {_FALLBACK_VERSION!r} but pyproject declares {declared!r}; "
        "bump both together or an uninstalled checkout misreports its own version"
    )
