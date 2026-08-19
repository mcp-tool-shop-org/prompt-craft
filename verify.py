#!/usr/bin/env python
"""Refuse if any hard-gate leg fails.

    python verify.py              # checkout: PYTHONPATH=src
    python verify.py --installed  # after pip install -e ".[dev]"
    python verify.py --audit      # + the dependency audit (needs the network)

Legs: version coherence (--installed only), lint, typecheck, the suite,
the suite under -O (gates must still raise), the wheel and sdist.
--basetemp is always set so Windows dead-symlink cleanup does not look
like a repo failure.

The dependency audit is a leg only under --audit, and off by default.
Not squeamishness: running it makes the gate *time-varying*, so the same
tree passes today and fails tomorrow when an advisory publishes. That is
correct for CI and wrong for a release gate, which should be a function
of the tree. Without --audit the summary says the audit did not run,
rather than letting a bare "VERIFY OK" imply a scope it does not have --
the same visible-skip doctrine ci.yml argues for under --skip-editable:
"could not check" must never read as "checked clean".

With --audit, three outcomes are distinguished rather than two. An
advisory with a published fix is actionable and fails. One with no
published fix is real but has nothing to upgrade to, so it is reported
without failing -- a gate that is permanently red with no move available
teaches people to skip gates. A distribution pip-audit could not check
at all is reported the loudest: on a box with [image], torch is a local
+cu130 build that is not on PyPI, so the largest dependency in the tree
is invisible to the audit. The run also names which extras were
installed, because the verdict depends on that set and two honest runs
on different boxes disagree without it.

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
import json
import os
import re
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


def _plural(n: int, one: str, many: str) -> str:
    """``1 advisory`` / ``2 advisories`` -- the counts get read by people."""
    return f"{n} {one if n == 1 else many}"


def _req_name(req: str) -> str:
    """Distribution name from a requirement string: ``dspy-ai>=2.5`` -> ``dspy-ai``."""
    return re.split(r"[<>=!~\[\s;(]", req, maxsplit=1)[0].strip()


def _is_installed(dist: str) -> bool:
    try:
        version(dist)
    except PackageNotFoundError:
        return False
    return True


def _installed_extras() -> list[str]:
    """Which of pyproject's optional-dependency groups are fully installed.

    The audit's verdict *depends on this set*, so a run that does not name it cannot be
    compared against another box. ``[synth]`` pulls dspy, which pulls diskcache, which
    carries an advisory with no published fix; ``[dev]`` alone does not, and CI installs
    only ``[dev]``. Two honest runs would disagree and neither could be trusted -- the
    same trap as measuring one ruff family under ``--select`` and reading it as the gate.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    groups = data["project"].get("optional-dependencies", {})
    return sorted(
        name
        for name, reqs in groups.items()
        if all(_is_installed(_req_name(r)) for r in reqs)
    )


def _split_audit(payload: dict) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Split a pip-audit JSON report into (fixable, unfixable, unauditable).

    Three categories, not two, because "could not check" must never read as "checked
    clean" -- the distinction this codebase is built around:

    * **fixable** -- an advisory with a published fix version. Actionable, so it fails.
    * **unfixable** -- ``fix_versions: []``. Real, but there is nothing to upgrade to.
      Failing on it makes the gate permanently red with no move available, which is how
      people learn to skip gates. Reported loudly instead.
    * **unauditable** -- pip-audit could not check the distribution at all. On a box with
      ``[image]`` that is torch and torchvision: a local ``+cu130`` build is not on PyPI,
      so the largest dependency in the tree is invisible to the audit. Silence there
      would be precisely the defect this gate exists to catch.

    pip-audit emits duplicate rows for the same advisory, so entries are deduped by
    (name, version, id); otherwise the counts overstate what was found.
    """
    fixable: list[tuple] = []
    unfixable: list[tuple] = []
    unauditable: list[tuple] = []
    seen: set[tuple] = set()
    for dep in payload.get("dependencies", []):
        name = dep.get("name", "?")
        ver = dep.get("version", "?")
        if dep.get("skip_reason"):
            # Skipped entries carry only name + skip_reason -- no version key at all.
            # The reason text already embeds the version where pip-audit knows it
            # ("torch (2.13.0+cu130)"), so inventing a placeholder would add noise.
            unauditable.append((name, dep["skip_reason"]))
            continue
        for vuln in dep.get("vulns", []):
            key = (name, ver, vuln.get("id"))
            if key in seen:
                continue
            seen.add(key)
            fixes = list(vuln.get("fix_versions") or [])
            entry = (name, ver, vuln.get("id"), fixes)
            (fixable if fixes else unfixable).append(entry)
    return fixable, unfixable, unauditable


def _audit(py: str, env: dict[str, str], ran: list[str]) -> tuple[list, list]:
    """Opt-in dependency audit. Returns the (unfixable, unauditable) caveats.

    Off by default on purpose: it needs the network, and it makes the gate
    *time-varying* -- the same tree passes today and fails tomorrow when an advisory
    publishes. That is correct for CI and wrong for a release gate, which should be a
    function of the tree. It runs last for the reason ci.yml already gives: a red audit
    on a tree whose suite is broken tells you nothing about the dependency.
    """
    cmd = [py, "-m", "pip_audit", "--skip-editable", "--format=json",
           "--progress-spinner", "off"]
    print(f"-- dependency audit: {' '.join(cmd)}")
    print(f"   extras installed: {', '.join(_installed_extras()) or 'none'}")
    proc = subprocess.run(
        cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        hint = (
            "pip-audit is not installed in this interpreter; `pip install pip-audit`"
            if "No module named pip_audit" in proc.stderr
            else f"exit {proc.returncode}; stderr: {proc.stderr.strip()[:400]}"
        )
        raise SystemExit(
            f"VERIFY FAIL: dependency audit -- no parseable report. {hint}. You asked "
            f"for the audit with --audit, so this refuses rather than reporting an "
            f"audit that did not run."
        ) from None

    fixable, unfixable, unauditable = _split_audit(payload)
    for name, ver, vid, _fixes in unfixable:
        print(f"   NO FIX PUBLISHED -- {name} {ver} {vid} (reported, not failed)")
    for name, reason in unauditable:
        print(f"   NOT AUDITABLE -- {name}: {reason}")
    for name, ver, vid, fixes in fixable:
        print(f"   FIXABLE -- {name} {ver} {vid} -> {', '.join(fixes)}")
    if fixable:
        raise SystemExit(
            f"VERIFY FAIL: dependency audit -- "
            f"{_plural(len(fixable), 'advisory', 'advisories')} with a published fix. "
            f"Upgrade rather than ignoring: --ignore-vuln would be lowering the gate to "
            f"make it green."
        )
    ran.append("dependency audit")
    return unfixable, unauditable


def _run(label: str, cmd: list[str], env: dict[str, str], ran: list[str]) -> None:
    """Run one leg; on success record its label in the caller's ``ran`` list.

    ``ran`` is threaded through rather than kept at module level. It was module-level
    for one commit, and a second in-process ``main()`` would have appended to the first
    run's list and printed a leg twice -- a summary drifting from what actually ran,
    which is precisely the defect the accumulator was introduced to prevent.
    """
    print(f"-- {label}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT, env=env, check=False)
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
    ap.add_argument(
        "--audit",
        action="store_true",
        help="also run the dependency audit (needs the network; off by default so "
             "the gate stays hermetic and a function of the tree)",
    )
    args = ap.parse_args(argv)

    env = os.environ.copy()
    if not args.installed:
        existing = env.get("PYTHONPATH", "")
        src = str(ROOT / "src")
        env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing

    ran: list[str] = []
    caveats: tuple[list, list] = ([], [])
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
        if args.audit:
            caveats = _audit(py, env, ran)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("VERIFY OK -- checked: " + ", ".join(ran))
    if args.audit:
        unfixable, unauditable = caveats
        bits = []
        if unfixable:
            bits.append(
                _plural(len(unfixable), "advisory", "advisories") + " with no published fix"
            )
        if unauditable:
            bits.append(
                _plural(len(unauditable), "distribution", "distributions")
                + " it could not audit at all"
            )
        if bits:
            print(
                f"QUALIFIED -- the audit found nothing actionable, but this is not a "
                f"clean bill: {' and '.join(bits)}, listed above. Could not check is "
                f"not checked clean."
            )
    else:
        print(
            "NOT CHECKED -- dependency audit. CI runs pip-audit as a separate step, "
            "so a green verify.py is not yet a green CI. Re-run with --audit to "
            "include it."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
