#!/usr/bin/env python
"""Refuse if any hard-gate leg fails.

    python verify.py              # checkout: PYTHONPATH=src
    python verify.py --installed  # after pip install -e ".[dev]"

Legs: the suite, the suite under -O (gates must still raise), the wheel
and sdist. --basetemp is always set so Windows dead-symlink cleanup does
not look like a repo failure.
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
