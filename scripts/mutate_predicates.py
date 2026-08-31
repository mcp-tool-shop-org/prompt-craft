#!/usr/bin/env python
"""One-off adversarial pass over the eleven compound predicates in core/.

Not a CI stage. Applies one mutant, runs the suite, restores the file.
A surviving mutant is a decorative test.

THIS SCRIPT REWRITES TRACKED SOURCE FILES IN PLACE. That is the job, not a
side effect -- a mutant has to be real for the suite to have any chance of
catching it -- so the safety here is consent, not capability. The sweep runs
only when it is asked for by name. A bare invocation describes and exits, and
so does --help, which used to be accepted silently and then ignored while the
full 20-cycle sweep ran anyway.

    POSIX        PYTHONPATH=src python scripts/mutate_predicates.py --run
    PowerShell   $env:PYTHONPATH="src"; python scripts/mutate_predicates.py --run

    --run          perform the sweep (one full suite run per mutant)
    --list         print the mutant table and exit, touching nothing
    --help         print this and exit, touching nothing
    --allow-dirty  sweep even though a target file has uncommitted changes

Each mutant is restored by a try/finally around the suite run, so every
interrupt Python can see -- Ctrl-C included -- still restores the file. What
that cannot cover is a kill that never reaches Python: taskkill /F, an
OOM-kill, a closed laptop, a CI-style timeout. Any of those, landing during
one of the back-to-back full suite runs this performs, leaves ONE tracked file
under src/pcraft/core/ holding a deliberately wrong predicate, with nothing
red to say so. Recover with:

    git checkout -- src/pcraft/core

That is also why the sweep refuses to start on a dirty tree: on a clean tree
the recovery above is exact and costs nothing, and on a dirty one it would
discard work this script never wrote.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SCRATCH = ROOT / ".pytest-scratch-mutate"
RECOVER = "git checkout -- src/pcraft/core"

# (id, path relative to ROOT, exact original snippet, mutant snippet, what the flip does)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    (
        "CQ58 drop first",
        "src/pcraft/core/contract/compile_questions.py",
        "if q.depends_on and q.depends_on in index:",
        "if q.depends_on in index:",
        "visit parent even when depends_on is None (None in index?)",
    ),
    (
        "CQ58 drop second",
        "src/pcraft/core/contract/compile_questions.py",
        "if q.depends_on and q.depends_on in index:",
        "if q.depends_on:",
        "visit parent even when the id is not in the DAG",
    ),
    (
        "L64 drop faction",
        "src/pcraft/core/contract/loader.py",
        'if contract.level == "faction" or contract.extends is None:',
        "if contract.extends is None:",
        "a faction with an accidental extends would try to merge",
    ),
    (
        "L64 drop extends",
        "src/pcraft/core/contract/loader.py",
        'if contract.level == "faction" or contract.extends is None:',
        'if contract.level == "faction":',
        "a character with extends=None falls through to lookup(None)",
    ),
    (
        "L108 drop None-guard",
        "src/pcraft/core/contract/loader.py",
        "if base_atom is not None and _SEVERITY_RANK[atom.severity] < _SEVERITY_RANK[base_atom.severity]:",
        "if _SEVERITY_RANK[atom.severity] < _SEVERITY_RANK[base_atom.severity]:",
        "KeyError / compare against missing base on a child-only atom",
    ),
    (
        "L108 invert <",
        "src/pcraft/core/contract/loader.py",
        "if base_atom is not None and _SEVERITY_RANK[atom.severity] < _SEVERITY_RANK[base_atom.severity]:",
        "if base_atom is not None and _SEVERITY_RANK[atom.severity] > _SEVERITY_RANK[base_atom.severity]:",
        "raising a severity is now the refuse; relaxing is allowed",
    ),
    (
        "H62 drop _counts",
        "src/pcraft/core/gate/harness.py",
        "return [v for v in self.verdicts if v.zone is Zone.FAIL and _counts(v)]",
        "return [v for v in self.verdicts if v.zone is Zone.FAIL]",
        "optional FAIL atoms enter the blocking set",
    ),
    (
        "H62 drop FAIL",
        "src/pcraft/core/gate/harness.py",
        "return [v for v in self.verdicts if v.zone is Zone.FAIL and _counts(v)]",
        "return [v for v in self.verdicts if _counts(v)]",
        "every required atom, including PASS, is a failed_required",
    ),
    (
        "H65 drop _counts",
        "src/pcraft/core/gate/harness.py",
        "return [v for v in self.verdicts if v.zone in (Zone.UNCERTAIN, Zone.SKIPPED, Zone.NA) and _counts(v)]",
        "return [v for v in self.verdicts if v.zone in (Zone.UNCERTAIN, Zone.SKIPPED, Zone.NA)]",
        "optional unconfirmed atoms enter uncertain_required",
    ),
    (
        "H69 drop _counts",
        "src/pcraft/core/gate/harness.py",
        "return [v for v in self.verdicts if _counts(v) and v.score is not None]",
        "return [v for v in self.verdicts if v.score is not None]",
        "optional scores count as the gate having run",
    ),
    (
        "H69 drop score",
        "src/pcraft/core/gate/harness.py",
        "return [v for v in self.verdicts if _counts(v) and v.score is not None]",
        "return [v for v in self.verdicts if _counts(v)]",
        "SKIPPED required atoms count as scored",
    ),
    (
        "H110 drop first",
        "src/pcraft/core/gate/harness.py",
        "if q.depends_on and q.depends_on in verdicts:",
        "if q.depends_on in verdicts:",
        "None in verdicts — parent gate misfires or TypeError",
    ),
    (
        "H110 drop second",
        "src/pcraft/core/gate/harness.py",
        "if q.depends_on and q.depends_on in verdicts:",
        "if q.depends_on:",
        "KeyError when parent has not been evaluated yet",
    ),
    (
        "H134 drop tier",
        "src/pcraft/core/gate/harness.py",
        "if tier == 1 and zone in (Zone.UNCERTAIN, Zone.FAIL) and 2 in verifiers:",
        "if zone in (Zone.UNCERTAIN, Zone.FAIL) and 2 in verifiers:",
        "escalate from T0/T2 as if they were T1",
    ),
    (
        "H134 drop zone",
        "src/pcraft/core/gate/harness.py",
        "if tier == 1 and zone in (Zone.UNCERTAIN, Zone.FAIL) and 2 in verifiers:",
        "if tier == 1 and 2 in verifiers:",
        "escalate even on a clean PASS",
    ),
    (
        "R53 drop rerolls",
        "src/pcraft/core/loop/retry_policy.py",
        "return self.inpaints <= 0 and self.reprompts <= 0 and self.rerolls <= 0",
        "return self.inpaints <= 0 and self.reprompts <= 0",
        "budget looks exhausted while rerolls remain",
    ),
    (
        "R90 drop budget",
        "src/pcraft/core/loop/retry_policy.py",
        "if len(failed) > 1 and budget.reprompts > 0:",
        "if len(failed) > 1:",
        "RESYNTH even when the reprompt budget is gone",
    ),
    (
        "R90 invert >1",
        "src/pcraft/core/loop/retry_policy.py",
        "if len(failed) > 1 and budget.reprompts > 0:",
        "if len(failed) >= 1 and budget.reprompts > 0:",
        "a single fail takes the multi-fail resynth path",
    ),
    (
        "V75 only norm-in-tok",
        "src/pcraft/core/synth/visual_inventory.py",
        "if any(norm in tok or (len(tok) >= 8 and tok in norm) for tok in allowed):",
        "if any(norm in tok for tok in allowed):",
        "drop tok-in-norm (short atom no longer matches a longer segment)",
    ),
    (
        "V75 only tok-in-norm",
        "src/pcraft/core/synth/visual_inventory.py",
        "if any(norm in tok or (len(tok) >= 8 and tok in norm) for tok in allowed):",
        "if any(tok in norm for tok in allowed):",
        "drop norm-in-tok (fragment of a claim no longer matches)",
    ),
    (
        "V75 always True",
        "src/pcraft/core/synth/visual_inventory.py",
        "if any(norm in tok or (len(tok) >= 8 and tok in norm) for tok in allowed):",
        "if True:",
        "every leftover segment is licensed — the guard cannot fire",
    ),
]


def _target_paths() -> list[str]:
    """The tracked files this sweep rewrites, repo-relative and slash-separated."""
    return sorted({rel for _name, rel, _old, _new, _why in MUTANTS})


def _consent_banner() -> str:
    """One line, printed before anything is touched, saying what is about to happen."""
    return (
        f"NOTE: this rewrites {len(_target_paths())} tracked files under src/pcraft/core/ "
        f"IN PLACE, one at a time, restoring each from a try/finally around the suite run. "
        f"A kill that never reaches Python (taskkill /F, OOM, a CI timeout) leaves one file "
        f"holding a wrong predicate. Recover with: {RECOVER}"
    )


def _dirty_from_porcelain(out: str, targets: set[str]) -> list[str]:
    """Target files carrying uncommitted changes, parsed from ``git status --porcelain``.

    Split out from the git call so the refusal can be exercised without putting a real
    working tree into the one state this script must never be run against.
    """
    dirty: list[str] = []
    for raw in out.splitlines():
        line = raw.rstrip()
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:  # rename: `R  old -> new`; the new name is the tracked one
            path = path.split(" -> ", 1)[1]
        path = path.strip('"').replace("\\", "/")
        if path in targets:
            dirty.append(path)
    return sorted(set(dirty))


def _git_porcelain(paths: list[str]) -> str | None:
    """``git status --porcelain`` for these paths, or None when git could not answer.

    None is not the empty string, and the difference is the point: a missing git, a
    detached checkout, anything that makes the question unanswerable must not arrive at
    the caller looking like "the tree is clean".
    """
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def _dirty_targets() -> list[str] | None:
    """Which target files are already modified; None when that could not be determined."""
    targets = _target_paths()
    out = _git_porcelain(targets)
    if out is None:
        return None
    return _dirty_from_porcelain(out, set(targets))


def _preflight(allow_dirty: bool) -> int:
    """0 when the sweep may start; a non-zero exit code, already explained, otherwise.

    The restore path writes back the text this script read at start, so a target file
    that arrives dirty loses whatever was in it. ``--allow-dirty`` is the override, and
    it is a flag rather than a prompt because this script is also run unattended.
    """
    if allow_dirty:
        return 0
    dirty = _dirty_targets()
    if dirty is None:
        print(
            "REFUSE: could not read `git status` for the target files, so this cannot tell "
            "a clean tree from a dirty one. Could not check is not checked clean. Pass "
            "--allow-dirty if you are certain the tree is clean.",
            file=sys.stderr,
        )
        return 2
    if dirty:
        print("REFUSE: files this sweep rewrites already have uncommitted changes:", file=sys.stderr)
        for path in dirty:
            print(f"  {path}", file=sys.stderr)
        print(
            f"Commit or stash them first. The restore writes back the text read at start, "
            f"and `{RECOVER}` -- the recovery if a hard kill interrupts the sweep -- would "
            f"discard them too. --allow-dirty overrides.",
            file=sys.stderr,
        )
        return 2
    return 0


def run_suite() -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [PY, "-m", "pytest", "-q", f"--basetemp={SCRATCH}", "--tb=no"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else f"exit {proc.returncode}"
    return proc.returncode, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--run",
        action="store_true",
        help="perform the sweep: rewrite each target file in place, run the suite against "
             "it, restore it. Required -- a bare invocation describes and exits.",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="print the mutant table and exit without touching anything",
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="sweep even though a target file has uncommitted changes (the restore writes "
             "back the text read at start, so those changes are lost)",
    )
    args = ap.parse_args(argv)

    if args.list:
        for name, rel, _old, _new, why in MUTANTS:
            print(f"{name:24} {rel}  ({why})")
        print(f"{len(MUTANTS)} mutants across {len(_target_paths())} files. Nothing was modified.")
        return 0

    if not args.run:
        print(_consent_banner())
        print(
            "Refusing to sweep without --run. `--list` prints the mutants and `--help` "
            "prints usage; neither touches a file."
        )
        return 2

    rc = _preflight(args.allow_dirty)
    if rc != 0:
        return rc

    print(_consent_banner(), flush=True)
    print("baseline...", flush=True)
    rc, summary = run_suite()
    print(f"  {summary}")
    if rc != 0:
        print("REFUSE: baseline suite is not green; not mutating")
        return 2

    results: list[str] = []
    for name, rel, old, new, why in MUTANTS:
        path = ROOT / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            results.append(f"MISSING  {name}: snippet not found")
            print(results[-1], flush=True)
            continue
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            rc, summary = run_suite()
        finally:
            path.write_text(original, encoding="utf-8")
            # Mutated .pyc will otherwise outlive the restore.
            for pyc in (ROOT / "src").rglob("__pycache__"):
                for f in pyc.glob("*.pyc"):
                    try:
                        f.unlink()
                    except OSError:
                        pass
        status = "KILLED" if rc != 0 else "SURVIVED"
        line = f"{status:8} {name}: {summary}  ({why})"
        results.append(line)
        print(line, flush=True)

    print()
    print("=== SURVIVORS ===")
    survivors = [r for r in results if r.startswith("SURVIVED") or r.startswith("MISSING")]
    if not survivors:
        print("(none)")
    else:
        for r in survivors:
            print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
