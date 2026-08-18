#!/usr/bin/env python
"""One-off adversarial pass over the eleven compound predicates in core/.

Not a CI stage. Applies one mutant, runs the suite, restores the file.
A surviving mutant is a decorative test.

    PYTHONPATH=src python scripts/mutate_predicates.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SCRATCH = ROOT / ".pytest-scratch-mutate"

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


def main() -> int:
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
