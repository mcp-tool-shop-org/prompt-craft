# Next session — start here

You should have read **`grok.md`** (the harness loads it via `AGENTS.md`: run rules,
lint-gate rules, the CI-equivalent verify method) and **`ADVISOR.md`** (standing state
and fences) before this file. This top section is current as of **2026-08-31**; then
measure HEAD and the suite yourself — do not reconstruct from chat.

**Seats (unchanged, Director's live word 2026-08-18):** Advisor is **Claude**. Executor
is a separate seat. Advisor-owns-README is **on**. You own code, tests, and CHANGELOG
Unreleased. Advisor owns README* + all seven translations, handbook, landing, PyPI/npm
copy, and the CHANGELOG body beyond Unreleased.

## Where you are (measured 2026-08-31, re-measure anyway)

Repo: `E:\AI\prompt-craft` — HEAD **`5549eab`** on `origin/main`, tree clean, tag
**`v1.0.1`** on it. **v1.0.1 IS PUBLISHED on both registries and was MEASURED, not
assumed**: PyPI JSON API answers `1.0.1` (https://pypi.org/project/prompt-crafter/1.0.1/)
and npm `dist-tags.latest` answers `1.0.1` with signed provenance (sigstore logIndex
2667977023). The Director approved the `release` environment gate in chat 2026-08-31;
run 33437273635 concluded success. This is the **first 1.x on either registry** —
v1.0.0 was tagged 2026-08-18 but its publish was never approved. Suite **1162** in the
blessed venv (1156 / 7 skipped in a bare `[dev]` CI-equivalent venv). CI green.
shipcheck: 21/21 checked pass, all hard gates.

The dogfood run that got here is **swarm-1788165870-6880** (dogfood-lab/testing-os
control plane): four health waves (107 findings), a Director-approved feature board
(132 fixed / 18 deferred / 5 rejected, tranches S1–S4 + S5–S7), a fifteen-step Phase 9
integration exam, its same-session remediation, and the full release sequence. The run
record, receipts, adjudications (#122, #125, both CORROBORATE), and the exam pair
(`phase9-report.md` / `phase9-remediation.md`) live in
`E:/AI/testing-os/swarms/swarm-1788165870-6880/`; `RUN-CLOSEOUT.md` there is the
authoritative close-out. The swarm is **closed**.

**Nothing is open in this repo.** If the Director does not name a job: measure HEAD,
re-count, stop. When the Director does name one, the standing backlog is:

1. **STABILITY.md ruling for the five new verbs** (`new`, `resolve`, `calibrate`,
   `regrade`, multi-image `gate`) — deliberately uncovered at 1.0.1 ("not named = not
   covered"); the ruling is owed next minor.
2. **Identity sub-gate evidence** — the fence holds (no delete, no promote, no wire;
   0.55/0.05 stay) until a Director ruling WITH holdout data. The v1.0.1 calibration
   workflow (`pcraft calibrate` / `regrade`, ~50–100 labelled sprites per check type)
   exists precisely to produce that evidence.
3. **The `[verify]` extra decision** — model-tier deps (`t2v-metrics`, `ai-eyes-mcp`)
   are bring-your-own by decision, censused by `pcraft doctor`; blessing an extra needs
   a GPU integration test of a real t2v-metrics version, and
   `tests/test_packaging.py::test_the_model_tier_modules_are_deliberately_in_no_extra`
   goes red to force the bookkeeping when it happens.
4. **Receipt-integrity design** — replay covers contract/DAG/threshold drift but not
   `decision`/`prompt`/`seed` (Phase 9 F3); and an escalated-without-scores run writes
   no receipt for `resolve` to consume (Phase 9 F6). Both are design questions, not
   patches.
5. **The 18 deferred board items** in the control-plane DB (handbook doc items
   consolidated under F-96c0f93a / F-a10f4e85; plugin exemplar; img2img; mutation
   receipts; shell completion; output-helper consolidation; a
   `scaffold_from_reference_sheet` verb).

```
cd E:\AI\prompt-craft
.\.venv\Scripts\python.exe -m pytest -q     # quick count, NO shared --basetemp
.\.venv\Scripts\python.exe verify.py        # blessed gate (fresh mkdtemp per run)
```

Method notes that earned their place this run: verify in a bare `[dev]` CI-equivalent
venv before push (the blessed venv has extras and has lied; typer floor is 0.27 there);
the blessed lint scope is `ruff check src tests verify.py` + `mypy src verify.py` —
`ruff check .` flags out-of-gate `scripts/` and misreads the floor; after any pyproject
version bump, `pip install -e ".[dev]"` in EVERY editable venv or dist-info serves the
old number; translations run BEFORE the tag, same commit as the README change; and
RELEASING.md owns the release sequence (two free dry-run rungs — rung two is proven by
REJECTING at the environment prompt).

---

# Everything below is the 2026-08-18 session record

Kept unedited per the receipt rule (rulings and receipts are appended, never rewritten).
**Superseded wherever it conflicts with the section above** — in particular: "Version
stays 1.0.0 unless the Director says bump", "Do not run Phase 10 / full treatment /
publish / tag", suite counts, and HEAD references are all of that era. The fences that
still hold are restated above.

---

Two items closed back to back, both verified on real runs:

- **ruff rule-set widening** (`f41d46b`) — 15 families declared, every `ignore` naming
  its reason. Do not re-litigate; the evidence is in the config comments.
- **CI 3.11 dependency-audit red** (`ef5f72e`) — ambient setuptools upgraded, not
  ignored. Both legs now land on setuptools 84.0.0 and the visible skip table survives.

**Director ruled 2026-08-18. Both items now have a go and are DONE except one deferral.**
Item 1.1 and 1.3 landed; item 1.2 (`--audit`) is deferred with its semantics already ruled
(below). Item 2's delete was authorised and run. The original text of both items is kept
below unedited -- the ruling is recorded against it, not in place of it.

---

## Item 1 — `verify.py` honesty (CLOSED 2026-08-18 — all three parts landed)

> **Director ruling, 2026-08-18.** Land **1.1 and 1.3 now**; hold **1.2 (`--audit`)** until
> its semantics were settled. They were, in the same ruling: **when `--audit` lands, it must
> fail on advisories that have a published fix and report-loudly-without-failing on those
> that do not.**
>
> That question was live because of a finding the Executor surfaced before implementation:
> `diskcache 5.6.3` carries **PYSEC-2026-2447 with no fix version published**. It is not a
> declared dependency -- `pip show` gives `Required-by: dspy`, so it arrives transitively
> through the `[synth]` extra. **CI never sees it** (CI installs `.[dev]` only), but the
> blessed `.venv` has `[synth]`. So a naive `--audit` would be permanently red on this box
> with no upgrade path while CI stayed green -- the exact inversion of the gap 1.2 exists to
> close, and the fastest way to train people to skip a gate. The repo already separates
> "could not check" from "checked clean"; this is a third category, *checked, real, no fix
> published*, and it gets reported rather than either failing or being ignored.
> `--ignore-vuln` remains refused.
>
> **1.1 and 1.3 landed.** Suite 344 (was 339; five new tests in `tests/test_verify_legs.py`).
>
> **1.2 LANDED 2026-08-18** on the Director's go, with the ruled semantics plus the
> Advisor's extras refinement. `--audit` is opt-in and off by default. Three outcomes, not
> two: fixable fails, no-published-fix is reported without failing, and **could-not-audit
> is reported loudest** -- a category found while building it, not before. On a box with
> `[image]`, pip-audit cannot check `torch` at all (a local `+cu130` build is not on PyPI),
> so a naive audit would have printed a clean bill while blind to the largest dependency in
> the tree. Both paths exercised live: FAIL on this rig (setuptools, exit 1) and QUALIFIED
> on the CI-equivalent `[dev]` venv (exit 0). Twelve offline tests. **This item is closed.**
>
> **Advisor note added on review, 2026-08-18 — one refinement for whoever builds 1.2.**
> The diskcache finding proves the audit's result **depends on which extras are installed**:
> `[synth]` surfaces it, `[dev]` alone does not, and CI only ever installs `[dev]`. So a
> report from one box is not comparable to a report from another unless it says what it was
> looking at. `--audit` must therefore **name the extras present in the environment it
> audited**, alongside the fix/no-fix split. Otherwise two honest runs disagree and neither
> can be trusted -- which is the same failure the `--select` override trap produced on ruff,
> in a different tool. The ruled fix/no-fix semantics are unchanged and correct.

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

## Open item 2 — the blessed `.venv` was lying (RESOLVED 2026-08-18)

> **Director gave the go; `pip uninstall pcraft` was run.** `pcraft 0.1.0` is gone;
> `prompt-crafter 0.3.0` remains; `import pcraft` and `pcraft.domains` both resolve under
> `src/`. Two things the original write-up did not anticipate, both checked before acting:
>
> 1. **Both distributions claimed `Scripts/pcraft.exe`.** The uninstall removed the *working*
>    0.3.0 CLI shim along with the stale dist. Predicted from the RECORD beforehand, backed
>    up, and repaired immediately with `pip install -e ".[dev]"`; `pcraft --version` reports
>    0.3.0 from the exe. Anyone repeating this on another box should expect the same.
> 2. **An empty directory skeleton survives** at `.venv/Lib/site-packages/pcraft/`
>    (six directories, **zero files**) -- it was never in the dist's RECORD, so pip does not
>    remove it. Nothing references it and nothing imports through it. Left in place: it is a
>    further delete, and it is inert.

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
- Version stays **1.0.0** unless the Director says bump. The pre-1.0 standing ruling is
  RETIRED — its flip criteria were met and v1.0.0 was tagged 2026-08-18 (see the RULING
  block below, kept unedited per the receipt rule; `STABILITY.md` is the promise).
  MEASURED 2026-08-31: the v1.0.0 publish was never approved — registries stop at
  0.4.0; the stale run was cancelled; v1.0.1 ships the healed tree.
- **Do not run Phase 10 / full treatment / publish / tag.** Not asked.
- `verify.py` 1.1 + 1.3 are **landed**. Do not implement `--audit` (1.2) until the
  Director says go; its semantics are already ruled and recorded above.
- **Do not `pip uninstall` anything further.** The one approved delete is done.
- Do not lower a gate to make it green.
- Do not re-open the ruff rejections in `[tool.ruff.lint]`. They carry their evidence.
- Do not touch README* / translations / handbook / landing / PyPI / npm copy — Advisor's.
  You may update **CHANGELOG Unreleased** for what you land.
- **`HANDOFF.md` and `ADVISOR.md`: Advisor owns the structure; the Executor owns the
  receipts.** Write a Director ruling or a completion receipt into `HANDOFF.md` **in the
  same sitting**, as a marked block against the original item text — never by editing or
  deleting that text. Do not route it through Advisor first: an Advisor session may not
  exist when the ruling lands, and a ruling that waits is a ruling that lives in a chat
  log, which is the single thing these files exist to prevent. Advisor reconciles the
  surrounding prose afterwards. The 2026-08-18 Executor did this correctly and asked
  whether they should have; they should, and the earlier fence list was ambiguous, not
  them.
- No mutmut, no dependabot. Gates `raise`, never bare `assert`. ASCII in tool output.
- Do not share a fixed `--basetemp` across seats; `verify.py` uses a fresh `mkdtemp`.
- Do not pull `FLUX.1-dev` (24 GB, gated). Do not start InstantID rewrites. Do not swap
  the per-asset loop onto `DSPySynthesizer`. None of these are next obvious steps.
- Path rule on this rig: `F:/AI/...` in old memory means `E:/AI/...`. No F: or G: drive.

## Small, unclaimed, no go needed beyond the usual

> **Both items below were RESOLVED 2026-08-18** (`25a7e91`, `e5af2e5`). `_RAN` is gone
> entirely — threaded as a local rather than reset, so there is no reset to forget, and
> two tests pin it: one that legs do not leak between callers, one that **a leg which
> exits non-zero is never recorded as checked**. That second test was not asked for and
> is the better half: the ordering of `ran.append` after the raise was incidental, and it
> is load-bearing. The skeleton is cleared; `pcraft` and `pcraft.domains` still resolve
> under `src/`, CLI still 0.3.0, all re-verified by Advisor. Original text kept below.

- **`verify.py`'s `_RAN` is module-level mutable state.** It is correct as run today —
  the script runs once per process and the new tests do not call `main()` — but a second
  in-process `main()` would append to the first run's list and print a summary naming a
  leg twice. That is the drift the list was introduced to prevent, one layer up. Reset it
  at the top of `main()` or thread it through as a local. Found in Advisor review, not by
  a gate; verified latent, not live.

  > **RESOLVED 2026-08-18 (Executor).** Reproduced first -- two in-process `_run` calls
  > gave `VERIFY OK -- checked: noop, noop` -- then **threaded through as a local**
  > rather than reset, so the state is gone rather than managed. `_RAN` no longer exists.
  > Two tests pin it: legs recorded into one caller's list do not leak into another's,
  > and a leg that exits non-zero is **not** recorded as checked. Suite **346**.
- **`.venv/Lib/site-packages/pcraft/`** survives the uninstall as six directories with
  **zero files** (verified: `find -type f` returns 0). Never in the dist RECORD, so pip
  left it. Nothing imports through it — `pcraft` and `pcraft.domains` both resolve under
  `src/`, verified. **Advisor recommends clearing it**: its only effect is to look like a
  shadowing hazard to the next person who audits this venv, which costs a real
  investigation to disprove. It is a delete, so it needs the Director's word.

## CLOSED 2026-08-18 on the Director's go — the gate now checks itself

> **Landed.** `ruff check src tests verify.py` and `mypy src verify.py`. Both were clean
> before and after, so the change cost nothing and the window did not have to be paid for.
> mypy 56 -> 57 files, no conflict with the pinned `packages = ["pcraft"]` — verified
> independently by the Executor against the real invocation, not the isolated proxy.
> Pinned by `test_the_gate_checks_the_file_that_defines_the_gate`, so a future edit cannot
> quietly narrow the targets back. Suite **359**.
>
> The original argument is kept below, because the reasoning is the reusable part.

## (was) Open — one item, verified free TODAY and decaying

**`verify.py` is not linted or typechecked by its own gate.** The legs are
`ruff check src tests` and `mypy src`; the gate checks everything except the file that
defines the gate. This is the same defect class as the three already fixed in this repo
(`[tool.ruff]` with no `select`; a bare `VERIFY OK`; mypy aborting on a numpy stub while
still reporting as configured) — and it is the fourth instance, in the gate itself.

Found by the Executor, who noticed only because they ran ruff on `verify.py` by hand and
it flagged `PLW1510` on a **pre-existing** line. They fixed both sites, so:

**Advisor verified the change that would actually land, not the isolated proxy:**

```
ruff check src tests verify.py     -> All checks passed
mypy src verify.py                 -> Success, 57 source files (was 56, no config conflict)
```

Both clean **right now**. That is the whole argument for doing it now: the cost is zero
today and rises the moment anyone edits `verify.py` again, because `verify.py` has grown
from a thin runner into a file with JSON parsing and category logic — exactly the kind of
code the gate exists for. It is two words added to two legs. It needs a Director go
because it widens what CI enforces.

## Resolved by Advisor, 2026-08-18 — the blessed `.venv` was non-compliant

The Executor found `--audit` failing on this box and correctly did not mutate the
environment. Advisor ran the remedy, which is an **upgrade, not a delete**, and is the
identical action the Director already approved for CI at `ef5f72e`:

```
.\.venv\Scripts\python.exe -m pip install -U setuptools     # 78.1.0 -> 84.0.0
```

Before: `VERIFY FAIL: dependency audit -- 2 advisories with a published fix`, exit 1.
After: exit 0, and the gate says the honest thing rather than a clean bill —

```
QUALIFIED -- the audit found nothing actionable, but this is not a clean bill:
1 advisory with no published fix and 3 distributions it could not audit at all.
Could not check is not checked clean.
```

Enforcing a setuptools floor on CI while the blessed box carried two fixable advisories
was incoherent. It is now consistent, and `--audit` on this box exercises the
report-without-failing path rather than the failing one.

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

---

# RULING 2026-08-18 -- what `1.0.0` would mean here. Recommendation: STAY PRE-1.0.

> Asked for a decision, not a survey, and told not to bump. Nothing was bumped, tagged,
> published, or released. `identity_subgate.py` was not touched. No public surface was
> edited -- every doc change below is **proposed**, for the Advisor to land.

## Receipts first

Measured at HEAD **`763d20f`** (not `5deb7dd` -- HEAD moved mid-session; `763d20f` is
comment-only in `.github/workflows/release.yml`, no source, no tests). Tree clean,
`origin/main` in sync. CI **green** at that HEAD (run `32207592767`).

CI-equivalent venvs built per leg, `pip` upgraded first, both resolving **ruff 0.16.3 /
mypy 2.3.1** -- matching CI, not this box:

| leg | result |
|---|---|
| 3.11.15 `verify.py --installed` | **VERIFY OK** -- version coherence 0.4.0/0.4.0, lint, mypy 57 files, suite, suite under `-O`, build |
| 3.13.13 `verify.py --installed` | **VERIFY OK** -- same six legs |
| suite, re-counted at `763d20f` | **359** |

**359 stands.** Counted after my own run, on a private `--basetemp`, no shared path.

**`npx @mcptoolshop/shipcheck audit` -> exit 0.** Checked 20, unchecked 0, skipped 17,
pass rate **100%**, `All hard gates pass. Ship it.` -- reported as run, not estimated.

## The rule conflict is not mechanical. It is documentary.

**The shipcheck 1.0.0 floor is prose, not a gate.** `auditCommand()` in
`@mcptoolshop/shipcheck@1.0.7` (`bin/shipcheck.mjs:158-213`) is a **markdown checkbox
parser**: it reads `SHIP_GATE.md`, counts `- [x]`, `- [ ] ... SKIP:` and bare `- [ ]`,
and exits 1 only when something is unchecked. It never opens `pyproject.toml`, never
reads a version, and contains no semver logic -- the only `version` strings in the whole
binary serve its own `--version` flag. That is why the audit returned **100% at 0.4.0**.

So rule 1 (`shipcheck-product-standards.md`: "repos at 0.x MUST be promoted to 1.0.0")
and this repo's standing pre-1.0 ruling have **never actually collided in CI**, and
cannot. The conflict is between two documents, and it is resolvable in a document.

**Caveat on that 100%, found while working the gate.** `SHIP_GATE.md:47` skips a
**hard-gate-D** item -- "version matches tag" -- with the justification *"no git tag
exists yet (pre-first-release scaffold) -- nothing to compare the manifest's 0.1.0
against."* Five tags exist: `v0.2.0`, `v0.2.1`, `v0.3.0`, `v0.4.0`. The premise expired
three releases ago. Two more checked items carry receipts asserting **v0.2.0** content.
The audit cannot see any of this, because it counts boxes rather than re-checking claims.
A skip whose reason has expired reads as handled while being inert -- the exact defect
class this repo has now closed four times, sitting inside the gate the Director would
lean on to authorise a 1.0.

## The analytical core: two categories, not one list

A 1.0 under semver is a promise about **API and behavioural stability** -- what callers
may depend on, and what requires a major bump to break. It is **not** a claim that the
pipeline makes a good picture. Sorting the honest-status table on that axis splits it
cleanly, and the split is the answer.

### Category A -- capability gaps a 1.0 could honestly ship with

Each re-verified against the tree, not taken from the table:

| gap | verified | why it does not block 1.0 |
|---|---|---|
| Identity sub-gate not in `orchestrate` | only import is `subdomains/sprite/__init__.py:11`; absent from `orchestrate.py` | it gates nothing, so it constrains no behaviour anyone can depend on |
| Example contract is a generic invention | both shipped contracts carry `_note: "GENERIC EXAMPLE -- NOT real canon"` | example **data**, not API |
| 5090 frame missed grip / sigil / bracer | as recorded | output quality is not a semver surface |
| Local Flux never run | `method=reference` raises `GATE_CLOUD_SUBMIT`; pose/IP/LoRA/InstantID refuse | a **documented refusal is a stable behaviour** |
| GEPA only on `hermes3:8b` | `sprite.synth.v1-gepa.json` -> `generated_by: gepa`; seed still `scaffold-seed` | model scale, off the hot path, Director-gated |
| Per-asset loop still `TemplateSynthesizer` | `cli/__init__.py:198` | implementation behind `synthesizer_iface`; the interface holds |

Filling any of these later is a **minor** bump by definition. All six are honestly
disclosable in a 1.0 release note. **If capability were the only issue, this repo could
go 1.0 today.**

### Category B -- genuine stability blockers, and they are NOT on the honest-status table

The table enumerates what the project has not *proven*. It does not enumerate what the
project has not *frozen*. That second list is where the real blockers are, and it is
undocumented.

**B1. The receipt format has no version and is fail-closed in both directions.**
`AssetRecord` fields: `record_id, contract_id, contract_hash, compiled_synth_id,
synth_backend, synth_degraded, generator_id, generator_family, seed, sampler,
conditioning, verifier_ids, thresholds_version, question_dag, gate_transcript,
retry_count, decision, attempts, checkpoint`. **No version field**, `extra="forbid"`.
Measured on a real receipt from `pcraft demo`:

```
FORWARD BREAK: IO_RECORD_INVALID -- one added field makes the whole receipt unreadable
BACKWARD BREAK: IO_RECORD_INVALID -- a receipt missing one field is unreadable
```

`replay` is a **shipped CLI command** whose entire purpose is reading receipts written by
earlier runs. Any future change to the record -- including one the roadmap plainly wants,
since wiring the identity sub-gate would add a sub-gate result to the transcript --
invalidates every receipt on disk, in both directions, with no version to branch on and
no migration path. This is the strongest blocker and it is nowhere in the docs.

**B2. The contract `$schema` version label is inert.** `Contract.schema_id` defaults to
`prompt-craft/contract.v1` (aliased `$schema`) and **nothing validates it**. Measured:

```
CONTRACT $schema v99 LOADED  -> version label is INERT, schema_id = prompt-craft/contract.v99-NONSENSE
```

The one mechanism that would let the contract format evolve compatibly is decorative.
Same shape as the finding in `763d20f` -- a boundary asserted on one side and not
required by the other.

**B3. The task's threshold hypothesis is half right, and the half matters.** The dispatch
proposed that thresholds with no holdout, backing a gate that blocks assets, are a
stability blocker. Measurement refines it:

- The **main gate** bands (`vqa` / `siglip2` / `palette`) live in
  `sprite.calibration.json`, versioned **`sprite.cal.v1`**, stamped into every receipt
  (`thresholds_version`, `orchestrate.py:417`, `harness.py:193`) and printed in the gate
  report. The file states its own status: *"GENERIC SEED - not a real human-labelled
  holdout."* Retuning these is a **declared data change, visible in every receipt** -- not
  a semver break, provided 1.0 says the table version is outside the semver contract.
- The **identity sub-gate's** `0.55` / `0.05` are different in kind: constructor defaults
  at `identity_subgate.py:35-36`, in **no table, no version, no receipt**. Retuning them
  later silently changes behaviour for any caller constructing the gate bare -- and that
  constructor is public via `SpriteSubdomain.identity_subgate(**kwargs)`.
- **But it blocks nothing today**, because it is not in `orchestrate`. So it is not a
  blocker for the gate that ships; it is a blocker for **freezing that constructor**. The
  fence forbids touching the file, so the fix is not code -- it is scoping the sub-gate
  explicitly *out* of the 1.0 promise.

**B4. `thresholds_version` is recorded but never enforced.** `replay()` raises
`STATE_REPLAY_DRIFT` on contract-hash drift and on question-DAG drift, and is **silent on
threshold drift**. A replay under a retuned table re-decides and reports no drift. If the
1.0 promise is "receipts are replayable," that is the hole in it.

**B5. The public surface has never been enumerated.** The only semver mention in the repo
is boilerplate at `CHANGELOG.md:6`. `src/pcraft/__init__.py` exports exactly
`package_version`; there is no `__all__` discipline, so every module path under `core/`
and `domains/` is de facto public. README's Support status says *"`main` is the only
supported state. No release channel, no backport policy, no SLA"* -- which is coherent
with 1.0 but is not a stability statement. **You cannot promise stability over a surface
you have not drawn.**

**B6. No `Development Status` classifier in `pyproject.toml`** -- there is no
`classifiers` key at all, so PyPI shows no maturity signal either way.

## The decision

**Stay pre-1.0 -- but retire the current reason for it.**

The standing ruling, *"a generate that ran is not a stability claim,"* reaches the right
conclusion from the wrong premise. It argues from **capability**, and capability is
Category A: six gaps, all documentable, none of them semver events. Held only by that
argument, the position quietly weakens every time a capability lands -- and it will
resurface at every release, exactly as it has now.

The defensible reason is Category B: **the two persisted formats a 1.0 would be
promising about are not ready to be frozen.** One has no version and is fail-closed in
both directions (measured). The other has a version nothing validates (measured). Neither
is on the honest-status table, so the project's own most useful artifact does not
currently surface its real blockers.

That reason is stronger, it is **checkable**, and it converts "pre-1.0, deliberately"
from a posture into a work item that ends.

## Criteria that flip it -- verifiable, not arguable

1. **`AssetRecord` carries `schema_version`, and `load()` branches on it.** Verified by: a
   v1 receipt loads under the v2 reader; an unknown future version raises a **named** code,
   not `IO_RECORD_INVALID`. Both directions pinned by tests.
2. **The contract `$schema` is validated.** Verified by: `prompt-craft/contract.v99` raises
   a named refusal; `contract.v1` loads. Today it accepts anything (measured above).
3. **`replay` asserts `thresholds_version`.** Verified by: replaying a receipt under a
   different threshold table raises drift instead of passing silently.
4. **A `STABILITY.md` enumerates the public surface** -- which CLI commands, which import
   paths, which on-disk formats semver covers, and what is explicitly excluded (named:
   threshold *table values*, everything under `subdomains/sprite/` while unwired,
   `core.optimize`). Verified by: the document exists and every name in it resolves.
5. **The identity sub-gate is named in that document as provisional and out of scope**,
   with `0.55` / `0.05` stated as unvalidated defaults. This satisfies the fence -- no
   delete, no promote, no wire -- and removes it as a blocker without touching the file.
6. **`Development Status :: 5 - Production/Stable`** added to `pyproject.toml` in the same
   commit as the bump. Verified by: it appears on the PyPI page.

Deliberately **not** on this list: a labelled holdout for the identity thresholds. It is
good work and it is Category A. Requiring it here would re-import the capability argument
this ruling is retiring -- an unwired gate needs a holdout before it is *wired*, not
before the package is *stable*.

## Free fix, owed regardless of the 1.0 decision -- and it is a live one

`src/pcraft/core/gate/thresholds.py:5` still states: *"Bands are calibrated against a
human-labelled holdout and stored versioned."* That is the **exact claim** `README.md:150`
and `site/src/content/docs/handbook/index.md:58` retract by name. The data file is honest;
the module docstring that defines the thresholds is not. A claim reading as established
while untrue, in the gate's own source, is the defect this project exists to catch -- the
fifth instance, and the first one found in `core/`.

It is a `src/` docstring, so it is the **Executor's** to land, not this seat's and not the
Advisor's. One sentence. Recommend it goes in the next sitting that touches `core/`.

## Reconciling the two rules so this does not resurface

`E:\AI\.claude\rules\shipcheck-product-standards.md` is outside this repo and is the
Director's file, so this is **proposed text, not a change made**:

> **Named exemption -- `mcp-tool-shop-org/prompt-craft`.** The v1.0.0 floor does not apply
> while this repo's published pre-1.0 position stands. Reason: two persisted wire formats
> (`AssetRecord` receipts, contract `$schema`) are not yet frozen -- receipts carry no
> version and reject both added and missing fields; the contract version label is not
> validated. Both measured 2026-08-18. The exemption **ends** when the six criteria in
> `HANDOFF.md` ("Criteria that flip it") are met; it is bounded by those criteria, not
> open-ended. Note that shipcheck does **not** enforce the floor mechanically -- `audit`
> parses `SHIP_GATE.md` checkboxes and never reads a version -- so this exemption
> reconciles two documents, not a failing gate.

Recording it there is what stops the next seat re-deriving this from scratch. The floor
rule keeps its purpose -- it exists to stop 0.x drifting forever -- because the exemption
expires on named, checkable conditions rather than on judgement.

## Also worth the Advisor's attention (proposed, not done)

- **The honest-status table should gain a stability row.** It is the best artifact in the
  repo and it currently enumerates only unproven *capability*. B1 and B2 are the items a
  1.0 reader most needs and cannot currently find.
- **`SHIP_GATE.md:47`'s expired SKIP** should be re-worked to a real check now that four
  release tags exist -- it is a hard-gate-D item, and "version matches tag" is precisely
  the check that would have caught the stale dist-info this repo hit **twice**.
- **`ADVISOR.md` Fences and `HANDOFF.md` Fences both still read "Version stays 0.3.0"**
  while the header of each says 0.4.0 shipped. Stale by one release, in the fence list.

## Compensators

Nothing irreversible was performed. No version change, no tag, no publish, no release, no
edit to `identity_subgate.py`, no edit to any public surface. The single mutation is this
appended block; its compensator is `git revert <sha>`, owner Executor. Two throwaway CI
venvs and a demo receipt live under the session scratch dir and need no undo.
