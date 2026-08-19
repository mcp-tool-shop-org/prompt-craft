# Next session — start here

You should have read **`grok.md`** (the harness loads it via `AGENTS.md`: run rules,
lint-gate rules, the CI-equivalent verify method) and **`ADVISOR.md`** (standing state
and fences) before this file. All three are current as of 2026-08-18. This one carries
the job. Then measure HEAD and the suite yourself — do not reconstruct from chat.

**Seats (2026-08-18, Director's live word):** Advisor is **Claude**. Executor is a
separate seat. Advisor-owns-README is **on**. You own code, tests, and CHANGELOG
Unreleased. Advisor owns README* + all seven translations, handbook, landing, PyPI/npm
copy, and the CHANGELOG body beyond Unreleased.

## Where you are (measured 2026-08-18, re-measure anyway)

Repo: `E:\AI\prompt-craft` — HEAD **`ef5f72e`** on `origin/main`, tree clean.
Version **0.3.0**. Suite **339**. **CI green on both legs** (run `32198885560`).

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q     # quick count, NO shared --basetemp
.\.venv\Scripts\python.exe verify.py        # blessed gate (fresh mkdtemp per run)
```

Two items closed back to back, both verified on real runs:

- **ruff rule-set widening** (`f41d46b`) — 15 families declared, every `ignore` naming
  its reason. Do not re-litigate; the evidence is in the config comments.
- **CI 3.11 dependency-audit red** (`ef5f72e`) — ambient setuptools upgraded, not
  ignored. Both legs now land on setuptools 84.0.0 and the visible skip table survives.

Nothing on the board has a Director go yet. **Read the two open items, then stop and ask.**

---

## Open item 1 — `verify.py` honesty (ADVISOR RULING, needs Director go)

The previous Executor was asked for a recommendation, not an implementation, and
delivered one. This is the ruling on it, recorded here so it stops living in a chat log.

**The defect, stated precisely.** `verify.py` prints a bare `VERIFY OK`. That token does
not name its own scope, and its scope is smaller than it reads: the dependency audit is
not in it. This is the same shape as the defect that created the script — per its own
docstring, lint and typecheck became legs because they were "configured in pyproject and
invoked by nothing," reading as live gates while inert.

**Rejected — audit on by default.** It makes the release gate *time-varying*: a commit
that verified green yesterday fails today when an advisory publishes, with no code
change. That is correct for CI and wrong for a release gate, which should be a function
of the tree (PIN_PER_STEP). It also puts a network call inside a gate that is presently
offline and hermetic. A category change, not a cleanup.

**Adopted — declare the scope, and add the check with real teeth:**

1. `verify.py` names what it did **and did not** check — e.g.
   `dependency audit: NOT RUN (CI runs this separately)` alongside the passing legs.
   This applies the repo's own visible-skip doctrine, the one `ci.yml` already argues for
   `--skip-editable` ("could not check" must never read as "checked clean"), to the
   gate's own output.
2. Add `--audit` as an opt-in leg so there is **one** definition of the gate that CI can
   share, instead of a script and a workflow step that disagree about what "verified"
   means. Default stays off; hermeticity is preserved.
3. **Add a version-coherence assertion under `--installed`:** the installed
   distribution's version must equal `pyproject.toml`'s. Offline, deterministic, cheap.

Item 3 is the one that pays for the session, and open item 2 is why.

## Open item 2 — the blessed `.venv` was lying, and half of it still is

Found by the Advisor while verifying the Executor's report. No gate caught it.

`package_version()` resolves `version("prompt-crafter")` from installed metadata and
falls back to the tree's literal **only on `PackageNotFoundError`**. Stale metadata is
*found*, so the fallback never fires and the wrong version returns silently.

On the blessed `.venv` — the interpreter `grok.md` names, the one every seat is told to
use — `pcraft --version` reported **0.2.1** against a **0.3.0** tree. That is exactly the
defect of `f23f345` ("Three tests asserted a version literal. A stale editable install
hid it"). The release-side fix landed; **the local environment was never re-installed**,
so the trap stayed armed on this box through the entire widening session.

**Half-repaired by the Advisor, non-destructively:** `pip install -e ".[dev]"` regenerated
the dist-info. `pcraft --version` now reports **0.3.0**; suite still **339**.

**Still open, and it needs a go because it is a delete (Hard Rule: Don't Delete):**
`.venv` also carries a stale `pcraft==0.1.0` distribution from the pre-rename package —
`pcraft-0.1.0.dist-info/`, `_editable_impl_pcraft.pth`, and a partial
`site-packages/pcraft/domains/` tree. It is **not** shadowing anything: `import pcraft`
resolves to `src/pcraft/__init__.py` and `pcraft.domains` resolves under `src/`, both
verified. So this is hygiene, not an active fault. Clearing it is `pip uninstall pcraft`.
**Do not run it without the Director saying so.**

**Why item 1.3 matters:** a version-coherence assertion under `--installed` would have
caught this the moment it appeared, and would have gone red on this box an hour ago. The
suite did not catch it because the quick-count recipe sets `PYTHONPATH=src` while
`package_version()` reads metadata regardless of `PYTHONPATH`. The gate and the lie were
looking at different things.

---

## What the previous Executor got right — keep these habits

- Verified the **exact specifier form that ships** (`pip install pip-audit "setuptools>=83"`),
  not the `--upgrade setuptools` form the handoff had verified with. They resolve the same;
  only one is the thing in the file.
- Confirmed the comment's claim from **both legs' logs** rather than asserting it: 3.13
  `Collecting setuptools>=83` installs 84.0.0 fresh with no uninstall; 3.11 reports
  `Found existing installation: setuptools 79.0.1` and upgrades.
- Found a local-only artifact the handoff missed: a fresh 3.11 venv also ships **pip 24.0**,
  which pip-audit flags for CVEs CI never sees, because `setup-python` provides a current
  pip. **Upgrade pip first** or you chase a finding that does not exist on the runner.
- Overturned their own draft caveat when the measurement contradicted it, and said so.

## Method — verify like CI, not like this box

Do not trust the local venv. It has now been wrong in **five** distinct ways on this repo:
ruff 0.15.16 vs CI's 0.16.3; mypy 2.1.0 vs 2.3.1, which emit *different error codes* so an
ignore named a code CI never produced; a stale editable dist-info reporting the previous
version (twice — at `f23f345`, and again today); and a stale `pip` reporting advisories the
runner does not have.

```
python -m venv <tmp>/civenv                      # once for 3.11, once for 3.13
<tmp>/civenv/Scripts/python -m pip install -q --upgrade pip    # DO THIS FIRST
<tmp>/civenv/Scripts/python -m pip install -e ".[dev]" build
<tmp>/civenv/Scripts/python -m ruff --version     # confirm it matches CI's resolve
<tmp>/civenv/Scripts/python verify.py --installed
```

`uv python list --only-installed` has 3.11.15 and 3.13.13. CI runs both.

## Compensators (NO SKIP)

| # | Action | Compensator (command) | Post-rollback state | Owner |
|---|---|---|---|---|
| C1 | `git push origin main` | `git revert <sha> && git push` (forward undo, **preferred**); `git push --force-with-lease origin ef5f72e:main` only if the push must vanish | Remote `main` at `ef5f72e`; CI returns to green on both legs | Executor |
| C2 | `verify.py` edit (open item 1) | `git checkout ef5f72e -- verify.py && git commit` | Gate back to bare `VERIFY OK`; no `--audit`, no coherence check | Executor |
| C3 | `pip uninstall pcraft` (open item 2) | `pip install -e ".[dev]"` re-creates a working install; the 0.1.0 dist-info itself is **not** recoverable | Blessed venv carries one editable dist, at 0.3.0 | Director approves; Executor runs |

C3 is the only genuinely destructive action on the board, and it is **gated on the
Director**. No publish, no tag, no `gh release create` this session.

## Fences

- `identity_subgate.py`: **no delete, no promote, no wire.** Thresholds 0.55 / 0.05 stay.
- Version stays **0.3.0** unless the Director says bump. Pre-1.0 is a standing ruling:
  a generate that ran is not a stability claim.
- **Do not run Phase 10 / full treatment / publish / tag.** Not asked.
- **Do not touch `verify.py`** until the Director rules on open item 1.
- **Do not `pip uninstall` anything** until the Director rules on open item 2.
- Do not lower a gate to make it green.
- Do not re-open the ruff rejections in `[tool.ruff.lint]`. They carry their evidence.
- Do not touch README* / translations / handbook / landing / PyPI / npm copy — Advisor's.
  You may update **CHANGELOG Unreleased** for what you land.
- No mutmut, no dependabot. Gates `raise`, never bare `assert`. ASCII in tool output.
- Do not share a fixed `--basetemp` across seats; `verify.py` uses a fresh `mkdtemp`.
- Do not pull `FLUX.1-dev` (24 GB, gated). Do not start InstantID rewrites. Do not swap
  the per-asset loop onto `DSPySynthesizer`. None of these are next obvious steps.
- Path rule on this rig: `F:/AI/...` in old memory means `E:/AI/...`. No F: or G: drive.

## Still out — only if the Director asks

1. Local Flux text-only / Fill — weights are not on disk.
2. Point the per-asset loop at `DSPySynthesizer` + the GEPA pin.
3. Phase 10 full treatment / publish.

## Same sitting as code

1. Re-count the suite. Quote only after that run.
2. Update `CHANGELOG.md` **Unreleased** for what you landed.
3. Verify CI on a real run before calling it done.
4. If you change something a public surface quotes, **tell Advisor** — do not edit
   README/handbook yourself in this multi-seat sitting.
