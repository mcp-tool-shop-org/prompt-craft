# Next session — start here

Read this file, then **`ADVISOR.md`**. Then measure HEAD and the suite. Do not
reconstruct this from chat. `grok.md` is the older Grok-seat operating file; where it
disagrees with this file or `ADVISOR.md` on seats, version, or counts, **this file
wins** (see the seat note below).

**Seats (2026-08-18, Director's live word):** Advisor is **Claude**. Executor is a
**new seat — you**. Advisor-owns-README is **on**. You own code, tests, and CHANGELOG
Unreleased. Advisor owns README* + all seven translations, handbook, landing, PyPI/npm
copy, and the CHANGELOG body beyond Unreleased.

## Where you are (measured 2026-08-18, re-measure anyway)

Repo: `E:\AI\prompt-craft` — HEAD **`f41d46b`** on `origin/main`, working tree clean.
Version **0.3.0**. Suite **339**. Quote the count only after your own run.

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q     # quick count, NO shared --basetemp
.\.venv\Scripts\python.exe verify.py        # blessed gate (fresh mkdtemp per run)
```

The ruff rule-set widening that v0.3.0 deferred is **DONE** (`f41d46b`).
`[tool.ruff.lint]` now declares 15 selected families and an `ignore` list where every
entry names the reason it is rejected. Do not re-litigate those rejections; the
evidence is in the config comments and the CHANGELOG Unreleased entry.

**One thing that changed for you as a contributor:** a `# type: ignore` on a
parenthesised import must sit on the statement's **first line**. isort now wraps long
imports, and mypy does not apply an ignore found on an inner line. That exact defect
was live in `cli/__init__.py` and is fixed. Do not recreate it.

**Measuring ruff, correctly:** `ruff check --select X` **overrides** the config's
select, so every suppression for a rule outside your override reads as dead. On this
tree `--select RUF100` reports 27 unused-noqa and the real gate reports 2. Measure with
a bare `ruff check`. Never autofix RUF100 under a `--select`.

## Your job — ONE item

**CI job `verify (3.11)` is red and must go green.** Run `32197333627`:
`verify (3.13)` succeeds, `verify (3.11)` fails at step 7, `dependency audit`.

This is **not** a regression from `f41d46b` — the `verify` step itself passed on both
legs, and the identical failure is present on the earlier run `32194862049`. It has
simply never been fixed.

**Root cause, measured, not guessed:**

| leg | ambient setuptools | audit |
|---|---|---|
| 3.13 | **not present** — 3.12+ venvs no longer bundle it | clean |
| 3.11 | **79.0.1**, ambient from `ensurepip` | PYSEC-2026-3447, fix in 83.0.0 |

`setuptools` is **not a dependency of this package**. pip-audit audits the
**environment**, not the declared dependency set, and the 3.11 environment carries a
setuptools that `prompt-craft` never asked for.

**The fix, verified in a CI-equivalent 3.11 venv before this file was written:**

```
python -m pip install -q --upgrade setuptools     # 79.0.1 -> 84.0.0
python -m pip_audit --skip-editable --progress-spinner off
# -> "No known vulnerabilities found", exit 0
```

`verify.py --installed` still passes on 3.11 after the upgrade (build runs in an
isolated hatchling env, so the ambient setuptools never reaches it).

Land it as a one-line change to the existing step at `.github/workflows/ci.yml:57`:

```yaml
      - name: install pip-audit
        run: python -m pip install pip-audit "setuptools>=83"
```

Add a comment above it saying **why**, in the register the rest of that file uses:
setuptools is ambient on 3.11 and is not a declared dependency; upgrading is the honest
fix, and `--ignore-vuln` would be lowering the gate to make it green. Name the
symmetric cost too — on 3.13 this **installs** a setuptools that was not there, which is
harmless and keeps the legs identical. Say it rather than leaving it to be noticed.

**Done means:** CI green on **both** legs on a real run, verified with
`gh run watch <id> --exit-status`. Not "the step looks right."

## Bring back a recommendation — do NOT implement

`verify.py` does not run the dependency audit; CI runs it as a separate step *after*
verify. So a contributor can get a green local `verify.py` while CI still fails — this
repo's own thesis defect, a gate that looks complete and is not. Folding pip-audit into
`verify.py` would close it, but puts a **network call** inside the blessed offline gate.
That is a real trade, not a cleanup. Write up the options and hand them to the Director.
Do not change `verify.py` this session.

## Standards compliance (scored 2026-08-18)

| # | Standard | Score | Evidence |
|---|---|:-:|---|
| 1 | PIN_PER_STEP | **3** | Both CI legs pinned (3.11 + 3.13); `ruff>=0.6,<0.17` and `mypy>=1.11,<3` bounded in `[dev]`; the fix is a version-floored install (`setuptools>=83`), not "latest" |
| 2 | ANDON_AUTHORITY | **3** | `verify.py` halts on the first failing stage and names it; CI `fail-fast: false` runs both legs so one red leg cannot hide the other's state; the audit step already halts the job |
| 3 | NAMED_COMPENSATORS | **2** | Table below; `COMPENSATORS.md` carries the repo-wide scaffold + run-time tables. Below 3 only because this session adds no new runtime action to `core/loop/compensators.py`, so it ships no receipt proving one works |
| 4 | DECOMPOSE_BY_SECRETS | **3** | The job touches one file for one reason (CI environment hygiene). The `verify.py` question is deliberately split out rather than folded in — a different thing that changes for different reasons |
| 5 | UNCERTAINTY_GATED_HUMANS | **3** | The one genuinely uncertain call is escalated contrastively rather than decided: "you probably expected this folded into `verify.py`; I am not deciding it, because it moves an offline gate onto the network" |
| 6 | EXTERNAL_VERIFIER | **3** | The verifier is GitHub Actions on ubuntu runners — different OS, fresh resolve, and not the seat that wrote the change. A local pass does not close this item; a real run does |

## Compensators (NO SKIP — irreversible actions this session takes)

| # | Action | Compensator (command) | Post-rollback state | Owner |
|---|---|---|---|---|
| C1 | `git push origin main` | `git revert <sha> && git push` (forward undo, **preferred**); `git push --force-with-lease origin f41d46b:main` only if the push must vanish | Remote `main` back at `f41d46b`; CI re-runs to the known green-3.13 / red-3.11 state | Executor |
| C2 | CI workflow edit | `git checkout f41d46b -- .github/workflows/ci.yml && git commit` | Audit step back to `pip install pip-audit`; 3.11 red again, 3.13 green | Executor |

No npm publish, no PyPI publish, no `gh release create`, no tag this session — so no
compensator is listed for them, because they may not happen. See the fences.

## Fences

- `identity_subgate.py`: **no delete, no promote, no wire.** Thresholds 0.55 / 0.05 stay.
- Version stays **0.3.0** unless the Director says bump. Pre-1.0 is a standing ruling:
  a generate that ran is not a stability claim.
- **Do not run Phase 10 / full treatment / publish / tag.** Not asked.
- Do not lower a gate to make it green. `--ignore-vuln` is the live temptation here.
- Do not re-open the ruff rejections in `[tool.ruff.lint]`. They carry their evidence.
- Do not touch README* / translations / handbook / landing / PyPI / npm copy — Advisor's.
  You may update **CHANGELOG Unreleased** for what you land.
- No mutmut, no dependabot. Gates `raise`, never bare `assert`. ASCII in tool output.
- Do not share a fixed `--basetemp` across seats; a path one seat writes can carry ACLs
  that deny the other on this rig. `verify.py` already uses a fresh `mkdtemp`.
- Do not pull `FLUX.1-dev` (24 GB, gated). Do not start InstantID rewrites. Do not swap
  the per-asset loop onto `DSPySynthesizer`. None of these are next obvious steps.
- Path rule on this rig: `F:/AI/...` in old memory means `E:/AI/...`. No F: or G: drive.

## Still out — only if the Director asks

1. Local Flux text-only / Fill — weights are not on disk.
2. Point the per-asset loop at `DSPySynthesizer` + the GEPA pin.
3. Phase 10 full treatment / publish.
4. The `verify.py` + pip-audit question above (recommendation only this session).

## Same sitting as code

1. Re-count the suite. Quote only after that run.
2. Update `CHANGELOG.md` **Unreleased** for what you landed.
3. Verify CI on a real run before calling it done.
4. If you change something a public surface quotes, **tell Advisor** — do not edit
   README/handbook yourself in this multi-seat sitting.
