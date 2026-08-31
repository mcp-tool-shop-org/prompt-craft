#!/usr/bin/env python
"""Smoke the BUILT WHEEL, from inside a throwaway venv that already has it installed.

    <venv-python> scripts/wheel_smoke.py --tree <repo root> --expect-version <X.Y.Z>

Driven by verify.py's ``wheel smoke`` leg, which builds the wheel, creates the venv, installs
the wheel into it non-editably, and then hands this script that venv's interpreter. It is a
plain script rather than a function inside verify.py because the two halves run in DIFFERENT
interpreters: everything here has to execute where the wheel is installed, not where the gate
is driven from.

WHY THIS EXISTS. verify.py's ``build`` leg produced a wheel into a scratch directory and then
deleted that directory -- wheel included -- before printing ``VERIFY OK``. Nothing ever
installed it, imported from it, or ran the console script it declares. Every other gate in
this repo (both ci.yml legs, release.yml, the suite) runs against ``pip install -e``, an
EDITABLE install that resolves ``pcraft`` straight out of ``src/`` and therefore never
exercises ``[tool.hatch.build.targets.wheel]`` at all.

That gap has teeth here specifically: ``src/pcraft`` ships 18 tracked non-Python files that
the runtime opens at import and gate time -- two compiled synth artifacts, the encoder rules
markdown, two example contracts, eleven pose/plate PNGs, the sprite calibration table, and
py.typed. A packaging rule that silently dropped one of them would still build, still install,
still ``import pcraft`` cleanly, and would fail only on the single runtime path that opens the
missing file. ``twine check`` does not close this: it validates METADATA, not contents.

WHAT THIS PROVES:

  * the wheel installs non-editably, and ``pcraft`` imports FROM THAT INSTALL. Asserted rather
    than assumed -- see ``_provenance``, which is the whole difference between this leg
    meaning something and this leg being theatre;
  * the installed distribution reports the version the tree declares;
  * ``[project.scripts]`` produced a console script that runs and prints that same version;
  * ``pcraft doctor --json`` -- GPU-free and network-free by design -- resolves the shipped
    contract store AND the shipped threshold table out of the installed package;
  * every git-tracked non-Python file under ``src/pcraft`` is present in the installed package
    directory. ``doctor`` alone reaches 3 of the 18; this check covers the rest.

WHAT THIS DOES NOT PROVE, said out loud because a leg reporting more scope than it has is this
repo's entire subject:

  * NOT dependency resolution. The wheel is installed ``--no-deps --no-index`` into a venv
    created with ``--system-site-packages``, so pydantic and typer come from the parent
    interpreter and no index is contacted. This says nothing about whether
    ``pip install prompt-crafter`` resolves on a clean machine. That needs the network, and it
    would make the gate time-varying the moment a dependency yanked a release -- the same
    reason the dependency audit is ``--audit``-only.
  * NOT the sdist. Only the wheel is installed here.
  * NOT any GPU, LLM, or diffusion path. ``doctor`` is the GPU-free command by design.
  * NOT that the shipped data files are CORRECT -- only that they arrived. Their contents are
    the suite's business.

Nothing below is written as a bare ``assert``. This script is a gate, and ``assert`` is
stripped under -O -- the exact disappearing-refusal shape verify.py's ``suite under -O`` leg
exists to catch. Refusals are explicit and carry the next move.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Sequence
from pathlib import Path

PACKAGE_PREFIX = "src/pcraft/"
"""Tree-relative prefix of the import package, as ``git ls-files`` prints it.

Forward slashes on every platform: ``git ls-files`` normalizes, measured on Windows.
"""


def _fail(message: str) -> int:
    print(f"WHEEL SMOKE FAIL: {message}", file=sys.stderr)
    return 1


def _tracked_data_files(ls_files_output: str, prefix: str = PACKAGE_PREFIX) -> list[str]:
    """Package-relative paths of the tracked NON-Python files, from ``git ls-files`` output.

    ``.py`` is the only extension dropped, deliberately. Anything else that is tracked inside
    the package is a file the wheel is expected to carry, so a newly added ``.pyi`` or ``.txt``
    is covered the day it lands rather than the day someone remembers to list it here.
    """
    out = []
    for raw in ls_files_output.splitlines():
        line = raw.strip()
        if not line or not line.startswith(prefix) or line.endswith(".py"):
            continue
        out.append(line[len(prefix):])
    return sorted(out)


def _missing_from_install(expected: Sequence[str], package_dir: Path) -> list[str]:
    """Which of ``expected`` the installed package directory does not actually contain."""
    return [rel for rel in expected if not (package_dir / rel).is_file()]


def _git_tracked(tree: Path) -> str | None:
    """``git ls-files -- src/pcraft`` from ``tree``, or None when git cannot answer.

    None, not ``""`` -- the distinction this codebase is built around. An empty string is a
    real answer meaning "nothing is tracked there"; a missing git, or a source tree that is
    not a checkout (an unpacked sdist, a vendored copy), makes the question unanswerable, and
    returning ``[]`` for it would hand the caller "could not check" wearing "checked clean".
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--", PACKAGE_PREFIX.rstrip("/")],
            cwd=tree, capture_output=True, text=True, check=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _provenance(package_dir: Path) -> str | None:
    """Refuse unless the imported package really is the one installed in THIS interpreter.

    The leg is worthless without this. A venv created with ``--system-site-packages`` can see
    the parent interpreter's editable install of this same project, and ``PYTHONPATH`` -- which
    verify.py sets to ``src`` for every OTHER leg -- is searched BEFORE a venv's own
    site-packages. Either one would let this script import ``pcraft`` from the source tree,
    pass every check below, and prove nothing whatsoever about the wheel. Both were measured:
    the venv's site-packages wins over a hatchling editable ``.pth``, and PYTHONPATH beats the
    venv, which is why verify.py strips it for this leg alone.
    """
    prefix = Path(sys.prefix).resolve()
    if prefix == Path(sys.base_prefix).resolve():
        return (
            f"this is not a virtual environment (sys.prefix == sys.base_prefix == {prefix}). "
            f"Run this script with the interpreter of the throwaway venv the wheel was "
            f"installed into, not with the ambient one."
        )
    try:
        package_dir.resolve().relative_to(prefix)
    except ValueError:
        return (
            f"pcraft imported from {package_dir}, which is OUTSIDE this venv ({prefix}). The "
            f"wheel is not what got imported -- a PYTHONPATH entry or an editable install of "
            f"this same project shadowed it, so every check below would have been measuring "
            f"the source tree. Clear PYTHONPATH for this run; verify.py's _wheel_smoke_env "
            f"does exactly that."
        )
    return None


def _console_script() -> Path | None:
    """The ``pcraft`` console script inside THIS interpreter's environment."""
    found = shutil.which("pcraft", path=sysconfig.get_path("scripts"))
    return Path(found) if found else None


def _run_cli(script: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the installed console script, decoding as UTF-8.

    The CLI chooses its own output encoding rather than inheriting the console codepage, so
    the decode side is pinned here too; ``errors="replace"`` keeps a mangled byte from
    surfacing as a UnicodeDecodeError traceback that hides the real result.
    """
    return subprocess.run(
        [str(script), *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=300,
    )


# Thirteen returns, and PLR0911 is rejected here rather than satisfied. Every one of them is
# a DIFFERENT refusal with its own remedy, in a fixed order where each check assumes the
# previous one passed -- collapsing them behind one shared result would trade thirteen
# specific messages for a single generic one, which is the defect this repo exists to catch
# arriving dressed as a tidiness improvement. (scripts/ is not in verify.py's lint leg today;
# this marker is here for the commit that changes that. Measured: covering scripts/ would
# surface 8 further pre-existing findings in the two older scripts.)
def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--tree", required=True, help="repo root the wheel was built from")
    ap.add_argument("--expect-version", required=True, help="the version pyproject declares")
    args = ap.parse_args(argv)

    tree = Path(args.tree).resolve()

    try:
        import pcraft
    except ImportError as exc:
        return _fail(
            f"the installed wheel does not import: {exc}. The wheel built and installed, so "
            f"this is packaging or a missing runtime dependency in the smoke venv, not a "
            f"build failure -- read it against [tool.hatch.build.targets.wheel] in "
            f"pyproject.toml."
        )

    package_dir = Path(pcraft.__file__).resolve().parent
    problem = _provenance(package_dir)
    if problem is not None:
        return _fail(problem)
    print(f"-- imported pcraft from {package_dir}")

    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("prompt-crafter")
    except PackageNotFoundError:
        return _fail(
            "pcraft imported from the venv but the prompt-crafter distribution has no "
            "metadata there. The package directory was placed without its dist-info, so "
            "`pcraft --version` and `pcraft doctor` would report the fallback literal as "
            "fact."
        )
    if installed != args.expect_version:
        return _fail(
            f"the installed wheel reports {installed}, the tree declares "
            f"{args.expect_version}. A wheel built from this tree cannot disagree with it: "
            f"either a stale artifact was installed, or the version was read from somewhere "
            f"other than pyproject."
        )

    script = _console_script()
    if script is None:
        return _fail(
            "no `pcraft` console script in this venv's scripts directory. "
            '[project.scripts] declares `pcraft = "pcraft.cli:app"`; the wheel installed '
            "without producing it, so `pip install prompt-crafter` would give a user the "
            "import package and no command."
        )

    proc = _run_cli(script, ["--version"], tree)
    expected_line = f"pcraft {args.expect_version}"
    if proc.returncode != 0 or proc.stdout.strip() != expected_line:
        return _fail(
            f"`pcraft --version` exited {proc.returncode} with stdout "
            f"{proc.stdout.strip()!r}, expected exit 0 and exactly {expected_line!r}. That "
            f"line is scripted against; stderr was: {proc.stderr.strip()[:400]!r}"
        )
    print(f"-- console script: {expected_line}")

    # `doctor` is the GPU-free, network-free command that opens shipped non-Python data: the
    # two example contracts and sprite.calibration.json. --json is read rather than the human
    # banner because the banner is prose that may legitimately be rewritten, while store_ok
    # and thresholds_version are the model's own fields.
    proc = _run_cli(script, ["doctor", "--json"], tree)
    if proc.returncode != 0:
        return _fail(
            f"`pcraft doctor` exited {proc.returncode} from the installed wheel. This is the "
            f"check that opens shipped non-Python data -- the contract store and "
            f"sprite.calibration.json -- so a packaging rule that dropped a data file lands "
            f"here. stdout: {proc.stdout.strip()[:600]!r} stderr: {proc.stderr.strip()[:600]!r}"
        )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _fail(
            f"`pcraft doctor --json` exited 0 but did not emit parseable JSON on stdout: "
            f"{proc.stdout.strip()[:400]!r}"
        )
    if not report.get("store_ok") or not report.get("thresholds_version"):
        return _fail(
            f"`pcraft doctor` reported store_ok={report.get('store_ok')!r} "
            f"thresholds_version={report.get('thresholds_version')!r} from the installed "
            f"wheel: {report.get('store_error')!r}. The shipped contract tree or the shipped "
            f"threshold table did not survive packaging."
        )
    print(
        f"-- doctor: store ok, {len(report.get('store_ids') or [])} contracts, "
        f"thresholds={report['thresholds_version']}"
    )

    listing = _git_tracked(tree)
    if listing is None:
        # Visible skip, not a silent pass. Same doctrine as verify.py's audit categories and
        # ci.yml's --skip-editable: "could not check" must never read as "checked clean". It
        # does not fail, because a gate that is permanently red on any non-checkout copy of
        # the tree, with no move available, is a gate people learn to skip.
        print(
            "NOT CHECKED -- the shipped-file manifest. git could not list the tracked files "
            f"under {PACKAGE_PREFIX} from {tree}, so only the data files `doctor` happens to "
            "open were proven present."
        )
        return 0

    expected = _tracked_data_files(listing)
    if not expected:
        return _fail(
            f"git tracks no non-Python files under {PACKAGE_PREFIX}, but this package ships "
            f"its rules, contracts, plates and threshold table as data. Either the tree is "
            f"not the one the wheel was built from, or this check is reading the wrong prefix."
        )
    missing = _missing_from_install(expected, package_dir)
    if missing:
        return _fail(
            f"{len(missing)} of {len(expected)} tracked non-Python files under "
            f"{PACKAGE_PREFIX} are NOT in the installed wheel: {', '.join(missing[:10])}"
            + (" ..." if len(missing) > 10 else "")
            + ". The wheel imports and the CLI runs, so nothing else in this gate would have "
            "noticed; the runtime path that opens the missing file is what would have. Fix "
            "[tool.hatch.build.targets.wheel] in pyproject.toml -- and note that force-include "
            "of a tree already covered by packages= is what collided last time, so do not "
            "re-add those mappings."
        )
    print(f"-- shipped data: {len(expected)} tracked non-Python files, all present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
