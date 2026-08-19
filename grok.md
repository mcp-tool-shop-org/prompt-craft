# prompt-craft — repo operating file

This file is the system for whichever seat the harness loads. Do not make the
Director re-explain any of it. The filename is historical — it was written for a
solo Grok seat and now serves every seat; `AGENTS.md` points here so the harness
loads it first.

Order: this file, then **`ADVISOR.md`** (standing state + fences), then
**`HANDOFF.md`** (the current job). Then measure HEAD and the suite yourself.

## Seats (2026-08-18)

This tree is **multi-seat**. Advisor is **Claude** (Director's word, 2026-08-18;
the seat was Grok before that). Executor is a separate seat.
Advisor-owns-README is **on**.

Executor lands code + tests + CHANGELOG Unreleased. Advisor moves README /
handbook / landing / PyPI / npm / translations, and the CHANGELOG body beyond
Unreleased.

If the tree is solo again, this fence turns off. See `ADVISOR.md`.

When you land code, in the **same sitting**:

1. Tests ride the change-set. Run them. Quote the count only after that run.
2. Move the honest-status table (README, handbook index, PyPI README, npm README)
   if the claim changed — or **tell Advisor** if that surface is not yours.
3. Update `CHANGELOG.md` Unreleased.
4. Update the seat's own memory store (see **Memory** below).

Do not leave "205 tests" / "unimplemented" claims after the wiring exists. That
already happened once.

## How to run

Do **not** share a fixed `--basetemp` across seats. A path this seat writes can
carry ACLs that deny the other seat on the same rig. `verify.py` already uses a
fresh `tempfile.mkdtemp` per run.

Quick count — no shared `--basetemp` (exit 0; cosmetic `pytest-current` atexit
noise is fine, and it can eat the summary line — pass your own private
`--basetemp` under your scratch dir if you need a clean count):

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q
```

Blessed full gate: `python verify.py` — version coherence (`--installed` only), lint,
typecheck, suite, suite under `-O`, build. It closes by naming **what it checked and what
it did not**: the dependency audit is not in it, CI runs pip-audit separately, so a green
`verify.py` is not yet a green CI. `--audit` is **built** and opt-in. It gives three
answers, not two: **fixable** advisories fail; **no published fix** is reported without
failing; **could not audit at all** is reported loudest — on any box with `[image]`,
pip-audit cannot see `torch` at all, so a two-category audit would print a clean bill
while blind to the largest dependency in the tree. Every run names the extras it resolved
against, because the finding set is a function of which extras are installed. A pass with
anything unresolved prints `QUALIFIED`, not `VERIFY OK`.

Python: `E:\AI\prompt-craft\.venv\Scripts\python.exe`.
`pip install -e ".[dev]"` also works (no PYTHONPATH).

`[image]` and `[synth]` are installed in this venv. The suite must stay GPU-free
anyway — stub `_load`, do not fire a live generate from a test.

### Verify like CI, not like this box

**Do not trust the local venv.** It has now been wrong in **five** distinct ways on
this repo: ruff 0.15.16 against CI's 0.16.3; mypy 2.1.0 against 2.3.1, which emit
*different error codes*, so an ignore named a code CI never produced; a stale
editable dist-info reporting the previous version — **twice**, at `f23f345` and
again on 2026-08-18; and a stale `pip` reporting advisories the runner does not
have. Three release attempts died in that gap before anyone built the right
environment.

Before pushing anything a release gate will judge, build a CI-equivalent venv per
leg and verify there:

```
python -m venv <tmp>/civenv                      # once for 3.11, once for 3.13
<tmp>/civenv/Scripts/python -m pip install -q --upgrade pip    # DO THIS FIRST
<tmp>/civenv/Scripts/python -m pip install -e ".[dev]" build
<tmp>/civenv/Scripts/python -m ruff --version     # confirm it matches CI's resolve
<tmp>/civenv/Scripts/python verify.py --installed
```

`uv python list --only-installed` has 3.11.15 and 3.13.13 on this rig. CI runs both.
Upgrade `pip` first or you will chase advisories the runner does not have: a fresh 3.11
venv ships pip 24.0, while `setup-python` provides a current pip.

**And do not trust `.venv`'s own metadata.** `package_version()` reads
`version("prompt-crafter")` from installed metadata and falls back to the tree's literal
*only* on `PackageNotFoundError` — so a **stale** dist-info is found, and returns the
wrong version silently. On 2026-08-18 `pcraft --version` reported 0.2.1 against a 0.3.0
tree, the same defect as `f23f345`. Re-run `pip install -e ".[dev]"` after any version
bump; the dist-info is not regenerated when `pyproject.toml` changes.

## The lint gate

`[tool.ruff.lint]` **declares** its rule set: 15 selected families plus an
`ignore` list where every entry names the reason it is rejected. It is not
inherited from whatever ruff version resolved — that is exactly what broke the
v0.3.0 release. `ruff>=0.6,<0.17` and `mypy>=1.11,<3` are bounded for the same
reason. Do not re-open those rejections; the evidence is in the config comments.

Two rules that will bite you:

- A `# type: ignore` on a **parenthesised** import must sit on the statement's
  **first line**. isort wraps long imports, and mypy does not apply an ignore
  found on an inner line. That defect was live in `cli/__init__.py` and is fixed.
- `ruff check --select X` **overrides** the config's select, so every suppression
  for a rule outside your override reads as dead. This tree reports 27 unused-noqa
  under `--select RUF100` and **2** against the real gate. Measure with a bare
  `ruff check`. Never autofix RUF100 under a `--select`.

## Fences

- Version stays **0.3.0** unless the Director says bump. Pre-1.0 is a standing
  ruling: a generate that ran is not a stability claim.
- `identity_subgate.py`: no delete, no promote, no wire. Thresholds 0.55 / 0.05 stay.
- No mutmut, no dependabot.
- Do not lower a gate to make it green. Widening a rule set and then blanket-ignoring
  what fires is the same defect as not widening it, with extra ceremony.
- Cloud Comfy is the default generate path. Local 5090 only if asked. The greened
  live 5090 generate and live GEPA compile **already ran**. See `ADVISOR.md`.
- GEPA is offline, `[synth]`, never on the per-asset hot path. `pcraft compile`
  does not invent a pixel metric.
- Gates `raise`, never bare `assert`. ASCII in tool output.
- Do not run Phase 10 / full treatment / publish / tag unless asked.
- Standing go to commit and push. Do not leave a finished change-set sitting
  uncommitted because an older line said "leave uncommitted unless asked."
- Path rule on this rig: `F:/AI/...` in old memory means `E:/AI/...`. No F: or G:
  drive. D: exists (external `AI-BACKUP`) — `Test-Path D:\` before writing to it.

## What is true (re-measure before quoting)

- **v0.3.0 shipped** to PyPI + npm 2026-08-18, after the verify gate held two
  failed release attempts. Suite last counted **359**. Re-count before quoting.
- The gate **checks itself**: the lint and typecheck legs cover `verify.py`, pinned by
  `test_the_gate_checks_the_file_that_defines_the_gate` so they cannot narrow back.
- The lint rule set is declared, not inherited (`f41d46b`). See above.
- **CI is green on both legs** (`ef5f72e`, run `32198885560`). The 3.11 leg had been
  red at `dependency audit` on an ambient `setuptools` 79.0.1 (PYSEC-2026-3447);
  Python 3.12+ venvs no longer bundle setuptools, which is why 3.13 was clean.
  setuptools is **not a dependency of this package** — pip-audit audits the
  environment, not the declared dependency set. Fixed by upgrading, not ignoring.
- SDXL: ControlNet OpenPose, IP-Adapter, LoRA, InstantID, regional inpaint —
  wired, fake-torch tested. InstantID and IP-Adapter cannot share one generate.
  Local `generate()` **ran** on the 5090 (2026-08-18, seed `169405236028824`,
  kind `controlnet_ip`). Looked at the frame: orcish; grip, sigil, bracer did not
  land. Two IP-Adapter plates stay on one adapter (all images; strongest scale).
- Flux: text-only and Fill inpaint are wired. Pose / IP-Adapter stay refused.
  `method=reference` writes the Cloud recipe and raises `GATE_CLOUD_SUBMIT`.
  Local Flux generate was **not** run — weights not on disk.
- Cloud recipe submitted live: job `06668d4c`. Looked at crop + fill.
- DSG Tier-2 expands entity / attribute / relation. Answerer may still share
  Tier-1 VQAScore weights (`shares_model_with`).
- Live GEPA compile ran on local Ollama `hermes3:8b` (not 600B). Pinned
  `sprite.synth.v1-gepa.json`. Seed `sprite.synth.v1.json` is still
  `scaffold-seed`. Per-asset loop still `TemplateSynthesizer`.
- Identity sub-gate is measured, not in `orchestrate`.
- `bind --no-mock` is the live door when `[image]` is installed. Missing extras
  are `DEP_IMAGE_MISSING`.

## Honest language

- Wired + fake-tested ≠ the plate landing in the pixels.
- A Cloud submit is not a local 5090 run. A 5090 run is not a lock.
- InstantID is wired on SDXL. Flux still refuses InstantID.
- A live GEPA compile on `hermes3:8b` is not a 600B compile.
- The shipped contract is a generic invention, not real canon.
- A green local gate is not a green CI. Both legs, on a real run.
- A suppression that looks live can be dead. Check that it still fires.

## Memory

Write to the store your seat actually reads.

- **Claude seats:** the canonical store is
  `C:\Users\mikey\.claude\projects\F--AI\memory\`, index `MEMORY.md`. This repo's
  paste-ready brief is `memory/prompt-craft-ci-311-audit-kickoff.md`. Any session
  that adds, moves, or deletes a file there must end by running `loadout-os refresh`.
- **Grok seats:** the database is `C:\Users\mikey\.grok\memory`, index `MEMORY.md`,
  repo topic `topics/prompt-craft-feature-pass.md`.
- `E:\AI\repo-knowledge` is neither of those.

The **repo** files (`ADVISOR.md` / `HANDOFF.md` / this one) win if a store drifts.

## Public surfaces

README.md, README.pypi.md, npm/README.md, `site/src/content/docs/handbook/`,
`site/src/site-config.ts`, `site/astro.config.mjs`. After README.md changes,
translations via
`node E:\AI\polyglot-mcp\scripts\translate-all.mjs E:\AI\prompt-craft\README.md`
**before** any tag or publish — a release tag pins whatever translations exist at
that commit, and releases are immutable.

Handbook build: `cd site && npm run build`. Need `site/dist/handbook/index.html`
and `site/dist/pagefind`.
