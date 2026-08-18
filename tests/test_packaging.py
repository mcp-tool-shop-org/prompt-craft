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


def test_version_is_pre_one_and_the_readme_agrees():
    """The version stays pre-1.0 deliberately, and the README may not drift from it.

    ⚑ REPLACES `test_version_stays_scaffold`, which pinned the literal `0.1.0`. That pin did its
    job — it caught the first bump rather than letting it pass silently — but "stays 0.1.0
    forever" is not an invariant anyone wants: it fires on every legitimate release. The two
    invariants that are actually load-bearing:

    1. **Still pre-1.0.** A live 5090 generate has now run, and `bind --no-mock` is
       the live door when `[image]` is installed. That is not a 1.x stability claim.
       Promoting the version should be a decision made on evidence, and deleting a
       failing assertion is not that.
    2. **The README cannot drift from it.** A front door advertising a version the package does
       not carry is this repo's own defect, one level up.
    """
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert int(version.split(".")[0]) == 0, (
        f"promoting to {version} needs an evidence-backed decision, not a test edit"
    )
    readme = Path("README.md").read_text(encoding="utf-8")
    assert f"v{version}" in readme, f"README does not state v{version}"


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
