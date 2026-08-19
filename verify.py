#!/usr/bin/env python
"""Refuse if any hard-gate leg fails.

    python verify.py              # checkout: PYTHONPATH=src
    python verify.py --installed  # after pip install -e ".[dev]"

Legs: version coherence (--installed only), lint, typecheck, the suite,
the suite under -O (gates must still raise), the wheel and sdist.
--basetemp is always set so Windows dead-symlink cleanup does not look
like a repo failure.

What this gate does NOT check is the dependency audit. CI runs pip-audit
as a separate step afterwards, so a green verify.py is not yet a green
CI. The summary says that out loud rather than letting a bare "VERIFY
OK" imply a scope it does not have -- the same visible-skip doctrine
ci.yml already argues for --skip-editable: "could not check" must never
read as "checked clean".

Version coherence is a leg because this environment has lied about the
version twice -- at f23f345, and again on 2026-08-18. package_version()
reads installed metadata and falls back to the tree literal *only* on
PackageNotFoundError, so a STALE dist-info is found and the wrong
version returns silently. The suite cannot catch it: the quick-count
recipe sets PYTHONPATH=src while the metadata read ignores PYTHONPATH
entirely. The gate and the lie were looking at different things.

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
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _declared_version() -> str:
    """The version pyproject declares.

    Read from the file, not imported from the package: importing would consult the
    same installed metadata this check exists to catch, and agree with itself.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _check_installed_version(installed: str, declared: str) -> None:
    """Refuse when installed metadata disagrees with the tree."""
    if installed != declared:
        raise SystemExit(
            f"VERIFY FAIL: version coherence -- the installed distribution reports "
            f"{installed}, pyproject declares {declared}. The editable install is stale; "
            f're-run `pip install -e ".[dev]"`. This is not cosmetic: package_version() '
            f"falls back to the tree literal only on PackageNotFoundError, so stale "
            f"metadata is found and returned silently by pcraft --version and pcraft "
            f"doctor."
        )


def _run(label: str, cmd: list[str], env: dict[str, str], ran: list[str]) -> None:
    """Run one leg; on success record its label in the caller's ``ran`` list.

    ``ran`` is threaded through rather than kept at module level. It was module-level
    for one commit, and a second in-process ``main()`` would have appended to the first
    run's list and printed a leg twice -- a summary drifting from what actually ran,
    which is precisely the defect the accumulator was introduced to prevent.
    """
    print(f"-- {label}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    if proc.returncode != 0:
        raise SystemExit(f"VERIFY FAIL: {label} exited {proc.returncode}")
    ran.append(label)


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

    ran: list[str] = []
    scratch = Path(tempfile.mkdtemp(prefix="pcraft-verify-"))
    try:
        py = sys.executable
        if args.installed:
            try:
                installed = version("prompt-crafter")
            except PackageNotFoundError:
                raise SystemExit(
                    "VERIFY FAIL: version coherence -- --installed was passed but the "
                    "prompt-crafter distribution is not installed in this interpreter."
                ) from None
            declared = _declared_version()
            print(f"-- version coherence: installed {installed} vs pyproject {declared}")
            _check_installed_version(installed, declared)
            ran.append("version coherence")
        # Static legs first: they are seconds, and a type error should not wait
        # behind a full suite + two builds to surface.
        _run("lint", [py, "-m", "ruff", "check", "src", "tests"], env, ran)
        _run("typecheck", [py, "-m", "mypy", "src"], env, ran)
        pytest = [py, "-m", "pytest", "-q", f"--basetemp={scratch / 't'}"]
        _run("suite", pytest, env, ran)
        env_o = env.copy()
        env_o["PYTHONOPTIMIZE"] = "1"
        _run("suite under -O", [py, "-O", "-m", "pytest", "-q",
                                f"--basetemp={scratch / 'to'}"], env_o, ran)
        dist = scratch / "dist"
        dist.mkdir()
        _run("build", [py, "-m", "build", "--outdir", str(dist)], env, ran)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("VERIFY OK -- checked: " + ", ".join(ran))
    print(
        "NOT CHECKED -- dependency audit. CI runs pip-audit as a separate step, so a "
        "green verify.py is not yet a green CI. See .github/workflows/ci.yml."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
