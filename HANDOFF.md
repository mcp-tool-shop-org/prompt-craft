# Next session — start here

Read `grok.md` first. Then **`ADVISOR.md`**. Then this file. Then
measure HEAD and the suite. Do not reconstruct this from chat.

**Seats (2026-08-18):** Advisor is Grok. Executor is Claude.
Advisor-owns-README is **on**. Both live-onlys already ran.
Identity sub-gate stays unwired. Version stays **0.2.1**.

## Where you are

Repo: `E:\AI\prompt-craft`
HEAD at handoff write: measure. Suite last counted **328**. Re-count.

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest --basetemp=E:\AI\prompt-craft\.pytest-tmp -q
```

Python: `E:\AI\prompt-craft\.venv\Scripts\python.exe`

You are the **Executor**. Advisor owns README / handbook / landing /
PyPI / npm / translations. You own the code + tests + CHANGELOG
Unreleased. Same sitting as code: tests. Quote the count only after
a run.

## What is already true (re-measure)

| thing | state |
|---|---|
| GPU-free suite | 328 |
| SDXL pose / IP-Adapter / LoRA / InstantID / inpaint | wired, fake-torch tested |
| Local 5090 `generate()` | **ran** 2026-08-18. Seed `169405236028824`, kind `controlnet_ip`. Frame: orcish; crossed arms, no two-hand axe, no triple-bar, no bone bracer. Notes in `records/_control_experiments/NOTES.md` (gitignored). |
| Two IP-Adapter plates | refuse: `Cannot assign 2 scale_configs to 1 IP-Adapter` |
| `bind --no-mock` | still `DEP_IMAGE_MISSING`, stays on the mock loop |
| Flux text + Fill | wired, fake-torch. Local Flux **not** run — `FLUX.1-dev` / Fill not on disk |
| Flux pose / IP / LoRA / InstantID | refuse (wrong family) |
| `method=reference` | writes Cloud recipe, `GATE_CLOUD_SUBMIT` |
| Cloud recipe | live job `06668d4c`. Keeper `records/_control_experiments/flux-fill-fist-only.png` |
| DSG | real expansion. Answerer may still share Tier-1 VQAScore |
| GEPA | live compile on Ollama `hermes3:8b` (not 600B). Pinned `src/pcraft/domains/image/compiled/sprite.synth.v1-gepa.json`. Seed `sprite.synth.v1.json` untouched. Per-asset loop still `TemplateSynthesizer`. CLI still `STATE_COMPILE_NEEDS_GATE`. |
| Identity sub-gate | measured, not in `orchestrate` |
| Shipped contract | generic invention, not real canon |

## This session's job

The two live-onlys are done. Full dispatch, ranked leftovers, and
fences live in **`ADVISOR.md`**.

If the Director does not name a job: measure HEAD, re-count, stop.

If the Director says continue, Advisor's first increment is:

1. Two IP-Adapter plates on one adapter (do not silently drop a plate).
2. `bind --no-mock` is not a door.

Do **not** start InstantID rewrites or identity-sub-gate wiring
unless the Director asks.

## Fences

- `identity_subgate.py`: no delete, no promote, no wire.
- Version 0.2.1 unless the Director says bump.
- No mutmut, no dependabot.
- Gates `raise`, never bare `assert`.
- Commit and push as you go when the Director has standing go.
