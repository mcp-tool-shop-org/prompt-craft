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


def test_version_stays_scaffold():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == "0.1.0"
