# Next session — start here

Read `grok.md` first. Then this file. Then measure HEAD and the suite.
Do not reconstruct this from chat.

**Director 2026-08-18:** this session is green for **both live-onlys**:
a local 5090 `generate()`, and a live GEPA compile. Identity sub-gate
stays unwired. Version stays **0.2.1**.

## Where you are

Repo: `E:\AI\prompt-craft`
HEAD at handoff write: **`c499f2d`** on `origin/main`. Re-measure.
Suite last counted **325**. Re-count before quoting.

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest --basetemp=E:\AI\prompt-craft\.pytest-tmp -q
```

Python: `E:\AI\prompt-craft\.venv\Scripts\python.exe`

You are the **only seat**. Advisor-owns-README is off. Same sitting as
code: tests, honest-status (README / handbook / PyPI / npm),
CHANGELOG Unreleased, translations if README.md changed, memory
`topics/prompt-craft-feature-pass.md`.

## How we got here (so you do not repeat it)

This dogfood swarm started as multi-seat. It switched to solo Grok
mid-stream without a catch-up brief. The seat treated a multi-seat
advisor fence as a stall and left the front door on **205 tests /
pose-lock unimplemented** after the encoders had already landed.
The Director called that. `grok.md` exists so it does not happen
again.

After that: Cloud recipe submitted live, real DSG, GEPA door wired,
Flux Fill, method=lora, InstantID. Public surfaces were brought
current. Encoder list is **done**.

## What is already true (re-measure)

| thing | state |
|---|---|
| GPU-free suite | 325 at `c499f2d` |
| SDXL pose / IP-Adapter / LoRA / InstantID / inpaint | wired, fake-torch tested |
| Flux text + Fill inpaint | wired, fake-torch tested |
| Flux pose / IP / LoRA / InstantID | refuse (wrong family) |
| `method=reference` | writes Cloud recipe, `GATE_CLOUD_SUBMIT` |
| Cloud recipe | live job `06668d4c`. Looked at crop + fill. Keeper `records/_control_experiments/flux-fill-fist-only.png` |
| DSG | real expansion. Answerer may still share Tier-1 VQAScore |
| GEPA | `compile_synthesizer` + `DSPySynthesizer` wired. **No live compile yet.** Per-asset loop still `TemplateSynthesizer` |
| Local 5090 `generate()` | **not run** |
| Identity sub-gate | measured, not in `orchestrate` |
| Shipped contract | generic invention, not real canon |

Cloud frames (gitignored): `records/_control_experiments/pcraft-recipe-crop.png`, `pcraft-recipe-fill.png`.

## This session's job — both live-onlys

Do them in this order. Look at every image you produce. Update the
honest-status table after each, not at the end.

### 1. Live local SDXL `generate()` on the 5090

1. Confirm CUDA: `.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"`
2. If `[image]` is missing: `pip install -e ".[image]"` in this venv. Do not invent a second env.
3. Generate ashen-reaver with the shipped two-hand OpenPose + identity plate (`method=ip_adapter`). Same seed as the Cloud stitch if you can: `169405236028824`.
4. Save under `records/_control_experiments/` (gitignored). Name it so the notes can point at it.
5. **Look at the frame.** Two-hand grip? Face? Sigil? Bracer? Write what you see in `records/_control_experiments/NOTES.md`.
6. If VRAM allows, a Flux text-only or Flux Fill pass is the rest of "SDXL/Flux generate". If it does not fit, say so. Do not OOM-loop.
7. Move the honest-status row: local generate has been run. Wired+faked ≠ this row.

`bind --no-mock` is a door if it still works; a small script that
calls `SDXLGenerator().generate(...)` is also fine. Do not silently
fall back to the stub.

### 2. Live GEPA compile

1. `pip install -e ".[synth]"` if `import dspy` fails.
2. Point DSPy at a real LM. Studio intent: 600B proposes offline,
   cheap local runs the pin. If 600B is not up, a local Ollama model
   is still a **live** compile — say which model you used. Do not
   pretend a 600B run happened.
3. Call `compile_synthesizer` from Python with an **external**
   `gate_metric(contract, prompt) -> [0,1]`. Do not score the LM's
   own text. A metric that generates + gates is the real one; a
   metric that gates an existing image against the synthesized
   prompt is acceptable if generate is too expensive to put inside
   the GEPA loop.
4. Pin a **new** artifact. Do not overwrite
   `sprite.synth.v1.json` in place as the seed. New version,
   `generated_by=gepa`.
5. The CLI still must not invent a pixel metric
   (`STATE_COMPILE_NEEDS_GATE`).
6. Update honest-status: a live compile ran, name the LM.

GEPA stays offline and off the per-asset hot path. Demo/bind still
use `TemplateSynthesizer` unless you deliberately swap.

## Fences

- `identity_subgate.py`: no delete, no promote, no wire.
- Version 0.2.1 unless the Director says bump.
- No mutmut, no dependabot.
- Gates `raise`, never bare `assert`.
- Commit and push as you go (Director standing for this swarm).

## After the two live runs

Update `grok.md` "What is true", README honest-status, handbook
index, PyPI, npm, translations, CHANGELOG Unreleased, and
`C:\Users\mikey\.grok\memory\topics\prompt-craft-feature-pass.md`.

Then stop and write the next handoff. Do not start InstantID
rewrites or identity-sub-gate wiring.
