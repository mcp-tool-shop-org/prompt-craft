# prompt-craft — Grok operating file

This file is the system for a **solo Grok seat** on this repo. Do not
wait for an advisor seat that is not here. Do not make the Director
re-explain these.

`AGENTS.md` points here so the harness loads it.

## You are the only seat

Advisor-owns-README is a **multi-seat** fence. It is off unless another
agent is editing this tree at the same time.

When you land code, in the **same sitting**:

1. Tests ride the change-set. Run them. Quote the count only after
   that run.
2. Move the honest-status table (README, handbook index, PyPI README,
   npm README) if the claim changed.
3. Update `CHANGELOG.md` Unreleased.
4. Update `topics/prompt-craft-feature-pass.md` in Grok memory.

Do not leave "205 tests" / "unimplemented" claims after the wiring
exists. That already happened once.

## How to run

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest --basetemp=E:\AI\prompt-craft\.pytest-tmp -q
```

Python: `E:\AI\prompt-craft\.venv\Scripts\python.exe`.
`pip install -e ".[dev]"` also works (no PYTHONPATH).

`[image]` and `[synth]` are now installed in this venv. The suite
must stay GPU-free anyway — stub `_load`, do not fire a live generate
from a test.

## Fences

- Version stays **0.2.1** unless the Director says bump.
- `identity_subgate.py`: no delete, no promote, no wire.
- No mutmut, no dependabot.
- Cloud Comfy is the default generate path. Local 5090 only if asked.
  The greened live 5090 generate and live GEPA compile **already ran**.
  See `HANDOFF.md`.
- GEPA is offline, `[synth]`, never on the per-asset hot path.
  `pcraft compile` does not invent a pixel metric.
- Gates `raise`, never bare `assert`. ASCII in tool output.
- Leave uncommitted unless asked. When asked to commit, push as you go.

## What is true (re-measure before quoting)

- Suite last counted **328**. Re-count before quoting.
- SDXL: ControlNet OpenPose, IP-Adapter, LoRA, InstantID, regional
  inpaint — wired, fake-torch tested. InstantID and IP-Adapter cannot
  share one generate. Local `generate()` **ran** on the 5090
  (2026-08-18, seed `169405236028824`, kind `controlnet_ip`). Looked
  at the frame: orcish; grip, sigil, bracer did not land. Two
  IP-Adapter plates on one adapter refuse before pixels.
- Flux: text-only and Fill inpaint are wired. Pose / IP-Adapter stay
  refused. `method=reference` writes the Cloud recipe and raises
  `GATE_CLOUD_SUBMIT`. Local Flux generate was **not** run — weights
  not on disk.
- Cloud recipe submitted live: job `06668d4c`. Looked at crop + fill.
- DSG Tier-2 expands entity / attribute / relation. Answerer may still
  share Tier-1 VQAScore weights (`shares_model_with`).
- Live GEPA compile ran on local Ollama `hermes3:8b` (not 600B).
  Pinned `sprite.synth.v1-gepa.json`. Seed `sprite.synth.v1.json` is
  still `scaffold-seed`. Per-asset loop still `TemplateSynthesizer`.
- Identity sub-gate is measured, not in `orchestrate`.
- `bind --no-mock` still raises `DEP_IMAGE_MISSING` and stays on the
  mock loop.

## Honest language

- Wired + fake-tested ≠ the plate landing in the pixels.
- A Cloud submit is not a local 5090 run. A 5090 run is not a lock.
- InstantID is wired on SDXL. Flux still refuses InstantID.
- A live GEPA compile on `hermes3:8b` is not a 600B compile.
- The shipped contract is a generic invention, not real canon.

## Memory

Grok's database is `C:\Users\mikey\.grok\memory`. Index is `MEMORY.md`.
This repo's handoff: `topics/prompt-craft-feature-pass.md`.
`E:\AI\repo-knowledge` is not that database.

## Public surfaces

README.md, README.pypi.md, npm/README.md, `site/src/content/docs/handbook/`,
`site/src/site-config.ts`, `site/astro.config.mjs`. After README.md
changes, translations via
`node E:\AI\polyglot-mcp\scripts\translate-all.mjs E:\AI\prompt-craft\README.md`
before any tag or publish.

Handbook build: `cd site && npm run build`. Need
`site/dist/handbook/index.html` and `site/dist/pagefind`.
