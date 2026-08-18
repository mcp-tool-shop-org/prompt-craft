#!/usr/bin/env python
"""Refuse if any hard-gate leg fails.

    python verify.py              # checkout: PYTHONPATH=src
    python verify.py --installed  # after pip install -e ".[dev]"

Legs: lint, typecheck, the suite, the suite under -O (gates must still
raise), the wheel and sdist. --basetemp is always set so Windows
dead-symlink cleanup does not look like a repo failure.

Lint and typecheck are legs here because they were configured in
pyproject and invoked by nothing -- no workflow, no script. That is how
the typecheck went inert unnoticed: once the [image] extra pulled numpy
2.5, mypy aborted on its PEP 695 stubs before checking a single pcraft
file, and still read as a configured gate. It hid 7 real errors. Both
tools ship in the [dev] extra this script already documents, so running
them is not a new dependency -- it is the gate finally being reachable.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _run(label: str, cmd: list[str], env: dict[str, str]) -> None:
    print(f"-- {label}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    if proc.returncode != 0:
        raise SystemExit(f"VERIFY FAIL: {label} exited {proc.returncode}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--installed",
        action="store_true",
        help="do not set PYTHONPATH=src; the package must already import",
    )
    args = ap.parse_args(argv)

    env = os.environ.copy()
    if not args.installed:
        existing = env.get("PYTHONPATH", "")
        src = str(ROOT / "src")
        env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing

    scratch = Path(tempfile.mkdtemp(prefix="pcraft-verify-"))
    try:
        py = sys.executable
        # Static legs first: they are seconds, and a type error should not wait
        # behind a full suite + two builds to surface.
        _run("lint", [py, "-m", "ruff", "check", "src", "tests"], env)
        _run("typecheck", [py, "-m", "mypy", "src"], env)
        pytest = [py, "-m", "pytest", "-q", f"--basetemp={scratch / 't'}"]
        _run("suite", pytest, env)
        env_o = env.copy()
        env_o["PYTHONOPTIMIZE"] = "1"
        _run("suite under -O", [py, "-O", "-m", "pytest", "-q",
                                f"--basetemp={scratch / 'to'}"], env_o)
        dist = scratch / "dist"
        dist.mkdir()
        _run("build", [py, "-m", "build", "--outdir", str(dist)], env)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
