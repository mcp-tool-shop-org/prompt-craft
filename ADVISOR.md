# Advisor dispatch — Claude is Executor

**Date:** 2026-08-18
**Swarm:** prompt-craft dogfood (`swarm-1787033129-beab` at `E:\AI\testing-os`)
**Advisor:** Grok (this file)
**Executor:** Claude
**Repo:** `E:\AI\prompt-craft`
**HEAD at write:** `e42ce2f` on `origin/main`
**Suite last counted:** **328** (re-count before quoting)

Read **`grok.md`**, then this file, then **`HANDOFF.md`**. Measure HEAD
and the suite. Do not reconstruct from chat.

---

## Seats (this is multi-seat again)

Advisor-owns-README is **on**. Claude executes code. Grok / Advisor
owns public surfaces (README*, handbook, landing, PyPI, npm,
CHANGELOG body beyond Unreleased, translations) unless the Executor
is explicitly told the tree is solo.

Executor still:

- rides tests on the change-set
- updates `CHANGELOG.md` Unreleased for the code that landed
- does **not** leave "unimplemented" claims in comments that the
  suite already proves
- does **not** bump version
- does **not** touch `identity_subgate.py` (no delete, no promote,
  no wire)

---

## How we got here (so you do not repeat it)

This swarm started multi-seat. It switched to solo Grok mid-stream
without a catch-up. The seat treated the advisor-owns-README fence
as a stall and left the front door on **205 tests / pose-lock
unimplemented** after the encoders had already landed. The Director
called that. `grok.md` exists so it does not happen again.

After that catch-up the encoder list was finished and both
live-onlys were greened and run. Public surfaces were brought
current. You are taking Executor **after** those live runs, not
instead of them.

---

## Swarm phase (honest)

| Phase | State |
|---|---|
| Health Stage A (0 CRIT / 0 HIGH) | **Closed** on `74a809b`. 8 CRIT + 13 HIGH. Identity fence held. |
| Stage A follow-on (inherited `enum`/`spatial`/`depends_on` freeze; must_have↔must_not id collision; `py.typed`) | Folded during the feature pass |
| Health B / C | Absorbed into the feature pass; not a labeled wave |
| Feature pass (encoders + live paths) | **Encoder list done. Both live-onlys done.** |
| Phase 9 — final test | **Not run** as a formal close |
| Phase 10 — full treatment / publish | **Not run.** No version bump. No npm/PyPI publish this swarm. |

The swarm is **not closed**. Feature work that was greened is done.
Closing the swarm is Phase 9 + 10 and needs an explicit Director go.

STANDARDS: **18 / 18** (scored 2026-08-18, named tests). Version
**0.2.1**. Do not bump.

---

## What is true (re-measure)

Python: `E:\AI\prompt-craft\.venv\Scripts\python.exe`

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest --basetemp=E:\AI\prompt-craft\.pytest-tmp -q
```

`[image]` and `[synth]` are installed in this venv. The suite must
stay GPU-free anyway. Tests that fall through to `_load` must stub
it. Do not fire a live generate from pytest.

| thing | state |
|---|---|
| GPU-free suite | **328** at `e42ce2f` |
| SDXL pose / IP-Adapter / LoRA / InstantID / inpaint | wired, fake-torch tested |
| Local 5090 `generate()` | **ran** 2026-08-18. Seed `169405236028824`, kind `controlnet_ip`. CUDA `torch 2.13.0+cu130`, RTX 5090, 31.84 GB. |
| That frame (looked at) | Orcish tusks. Crossed arms. Scythe, not a two-hand axe. No triple-bar. No bone-spike bracer. Same species, different character. Notes: `records/_control_experiments/NOTES.md` (gitignored). |
| Two IP-Adapter plates | refuse: `Cannot assign 2 scale_configs to 1 IP-Adapter`. The assembled ashen-reaver contract (faction costume + character face) cannot generate without dropping a plate. |
| `bind --no-mock` | still `DEP_IMAGE_MISSING`, stays on the mock loop. Not a door. |
| Flux text + Fill | wired, fake-torch. Local Flux **not** run — `FLUX.1-dev` / Fill not on disk. Token can see both (gated auto). A 24 GB pull was not started. |
| Flux pose / IP / LoRA / InstantID | refuse (wrong family) |
| `method=reference` | writes Cloud recipe, `GATE_CLOUD_SUBMIT` |
| Cloud recipe | live job `06668d4c`. Crop in-graph (no diptych). Fill kept the bracer. Keeper `records/_control_experiments/flux-fill-fist-only.png` |
| DSG | real expansion (entity / attribute / relation). Answerer may still share Tier-1 VQAScore (`shares_model_with`) |
| GEPA | live compile on Ollama **`hermes3:8b`** (not 600B). Pinned `src/pcraft/domains/image/compiled/sprite.synth.v1-gepa.json`. Seed `sprite.synth.v1.json` still `scaffold-seed`. Per-asset loop still `TemplateSynthesizer`. CLI still `STATE_COMPILE_NEEDS_GATE`. DSPy 3.3 needs `reflection_lm`; runner passes `dspy.settings.lm`. |
| Identity sub-gate | measured, **not** in `orchestrate`. Thresholds 0.55 / 0.05 have no holdout. |
| Shipped contract | generic invention, not real canon |
| CLIP on the live prompt | truncated 91 > 77. Boilerplate dropped. Load-bearing atoms were in the first 77. |

### Honest language (do not walk this back)

- Wired + fake-tested ≠ the plate landing in the pixels.
- A Cloud submit is not a local 5090 run. A 5090 run is not a lock.
- A live GEPA compile on `hermes3:8b` is not a 600B compile.
- InstantID is wired on SDXL. Flux still refuses InstantID.

---

## Fences (Executor)

- `identity_subgate.py`: **no delete, no promote, no wire.**
- Version **0.2.1** unless the Director says bump.
- No mutmut, no dependabot.
- Gates `raise`, never bare `assert`. ASCII in tool output.
- Cloud Comfy is the default generate path. Local 5090 only if asked.
  The greened live generate **already ran** — do not re-run it to
  "confirm" unless the Director asks.
- GEPA stays offline, `[synth]`, never on the per-asset hot path.
  `pcraft compile` does not invent a pixel metric.
- Do not start InstantID rewrites.
- Do not pull `FLUX.1-dev` (24 GB gated) unless asked.
- Do not swap the per-asset loop onto `DSPySynthesizer` unless asked.
- Do not run Phase 10 / publish / tag unless asked.
- Armature (`E:\AI\armature`) has foreign dirty index work. Leave it.

Path rule on this rig: `F:/AI/...` in old memory means `E:/AI/...`.
No F: or G: drive. D: exists (`AI-BACKUP`) — `Test-Path D:\` before
writing to it.

---

## Recommended next increment (Advisor ruling)

If the Director does **not** name a job: measure HEAD, re-count the
suite, stop.

If the Director says continue, do **these two first**, in this
order. Both are live-measured doors. Both are GPU-free.

### 1. Two IP-Adapter plates on one adapter

The shipped ashen-reaver contract assembles two `method=ip_adapter`
refs (faction costume + character face). `SDXLGenerator` loads one
adapter and then `set_ip_adapter_scale` with two scales. Live miss:
`Cannot assign 2 scale_configs to 1 IP-Adapter`.

The 5090 run dropped the costume plate so generate could fire. That
is a workaround, not a fix.

Fix the generator so the assembled contract can generate, or refuse
with a coded error that names the real constraint. Do not silently
drop a plate. Tests ride the change-set. Do not fire a live GPU
generate from pytest.

### 2. `bind --no-mock` is not a door

`pcraft bind --no-mock` raises `DEP_IMAGE_MISSING` and still runs
the mock loop. `[image]` is installed. The flag lies.

Make `--no-mock` either (a) call the real generator with a coded
refuse if extras/GPU are missing, or (b) stay refused but stop
claiming a missing extra when the extra is present. Do not silently
fall back to the stub.

### After those, only if asked

3. Local Flux text-only / Fill — weights are not on disk.
4. Point the per-asset loop at `DSPySynthesizer` + the GEPA pin.
   Demo/bind stay on `TemplateSynthesizer` until that swap is
   deliberate.
5. Phase 9 formal final test, then Phase 10 full treatment.

Do **not** start identity-sub-gate wiring or InstantID rewrites
as a "next obvious step." They are not.

---

## Same sitting as code (Executor)

1. Re-count the suite. Quote only after that run.
2. Leave public-surface honest-status to Advisor **unless** you
   were told the tree is solo. You may still update CHANGELOG
   Unreleased for the code you landed.
3. If you must change a comment that the README quotes, tell
   Advisor. Do not rewrite README.md yourself in this multi-seat
   sitting.

---

## Memory

Grok's database is `C:\Users\mikey\.grok\memory`.
Topic: `topics/prompt-craft-feature-pass.md`.
The **repo** file (`ADVISOR.md` / `HANDOFF.md` / `grok.md`) wins
if the store drifts.
