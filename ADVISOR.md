# Advisor dispatch — new Executor seat

**Date:** 2026-08-18
**Advisor:** Claude (this file). Seat changed by the Director's live word on 2026-08-18;
the prior Advisor seat was Grok. `grok.md` and `AGENTS.md` were brought current the same
day and no longer read from that arrangement.
**Executor:** new seat
**Repo:** `E:\AI\prompt-craft` (`mcp-tool-shop-org/prompt-craft`)
**HEAD at write:** `1503769` on `origin/main`, tree clean. **CI green on both legs.** Nothing open in the repo.
**Version:** **1.0.0** (shipped to PyPI + npm 2026-08-18, tag `v1.0.0`; `STABILITY.md` is the promise)
**Suite last counted:** **394** (2026-08-31; re-count before quoting)
**Released:** v1.0.0 — both registries confirmed; handbook + all seven translations current at the tag; the pre-1.0 ruling is RETIRED (its flip criteria were met — see the RULING block in `HANDOFF.md`)

Read **`HANDOFF.md`** first — it carries this session's job and the verified fix.
This file is the standing state and the fences. Measure HEAD and the suite yourself.
Do not reconstruct from chat.

---

## Seats

Advisor-owns-README is **on**. The Executor lands code, tests, and CHANGELOG
**Unreleased**. Advisor owns public surfaces — `README*` and all seven translations,
handbook, landing page, PyPI/npm copy, and the CHANGELOG body beyond Unreleased.

The Executor still:

- rides tests on the change-set and quotes the count only after a run
- updates `CHANGELOG.md` Unreleased for the code that landed
- does **not** bump version
- does **not** touch `identity_subgate.py` (no delete, no promote, no wire)
- **tells** Advisor when a change alters something a public surface quotes, rather
  than editing that surface

## Where the project actually is

| Phase | State |
|---|---|
| Health Stage A | **Closed** on `74a809b` (8 CRIT + 13 HIGH; identity fence held) |
| Feature pass (encoders + live paths) | **Closed.** Encoder list done, both live-onlys run |
| Phase 9 — final test / typecheck restore | **Closed** (`b4320fe`, `4a14db0`) |
| v0.3.0 release | **Shipped** 2026-08-18 to PyPI + npm after two verify-gate failures held it |
| ruff rule-set widening (v0.3.0's one deferred item) | **Closed** (`f41d46b`) |
| CI 3.11 dependency-audit red | **Closed** (`ef5f72e`) — ambient setuptools upgraded, not ignored; both legs green on run `32198885560` |
| Phase 10 — full treatment / publish | **Run 2026-08-18** on the Director's go. README + handbook updated, translations regenerated BEFORE the tag, v0.4.0 published to both registries by OIDC |

The swarm is **not closed**. Closing it is Phase 10 and is not authorised.

## What is true (re-measure before quoting)

Python: `E:\AI\prompt-craft\.venv\Scripts\python.exe`. `[image]` and `[synth]` are
installed in that venv; the suite must stay GPU-free regardless — stub `_load`, never
fire a live generate from a test.

| thing | state |
|---|---|
| GPU-free suite | **359** |
| Lint gate | **Declared**, not inherited. 15 families selected; every `ignore` names its reason. `ruff>=0.6,<0.17`, `mypy>=1.11,<3` |
| CI | **green on both legs** (`ef5f72e`, run `32198885560`). Both land on setuptools 84.0.0; the visible skip table survives |
| SDXL pose / IP-Adapter / LoRA / InstantID / inpaint | wired, fake-torch tested |
| Local 5090 `generate()` | **ran** 2026-08-18. Seed `169405236028824`, kind `controlnet_ip`, torch 2.13.0+cu130, RTX 5090 |
| That frame (looked at) | Orcish tusks, crossed arms, scythe not a two-hand axe, no triple-bar, no bone-spike bracer. Same species, different character |
| Two IP-Adapter plates | both images on one adapter; scale is the strongest requested lock. Do not drop a plate |
| `bind --no-mock` | live door when `[image]` is present; `DEP_IMAGE_MISSING` only if the extra is actually missing |
| Flux text + Fill | wired, fake-torch. Local Flux **not** run — `FLUX.1-dev` / Fill not on disk |
| Flux pose / IP / LoRA / InstantID | refuse (wrong family) |
| `method=reference` | writes the Cloud recipe, raises `GATE_CLOUD_SUBMIT` |
| Cloud recipe | live job `06668d4c`. Crop in-graph. Keeper `records/_control_experiments/flux-fill-fist-only.png` |
| DSG | real Tier-2 expansion (entity / attribute / relation). Answerer may still share Tier-1 VQAScore (`shares_model_with`) |
| GEPA | live compile on Ollama **`hermes3:8b`** (not 600B). Pinned `sprite.synth.v1-gepa.json`; seed still `scaffold-seed`. Per-asset loop still `TemplateSynthesizer`. CLI still `STATE_COMPILE_NEEDS_GATE` |
| Identity sub-gate | measured, **not** in `orchestrate`. Thresholds 0.55 / 0.05 have no holdout |
| Shipped contract | a generic invention, not real canon |
| CLIP on the live prompt | truncated 91 > 77; boilerplate dropped, load-bearing atoms were in the first 77 |

### Honest language (do not walk this back)

- Wired + fake-tested is not the plate landing in the pixels.
- A Cloud submit is not a local 5090 run. A 5090 run is not a lock.
- A live GEPA compile on `hermes3:8b` is not a 600B compile.
- InstantID is wired on SDXL. Flux still refuses InstantID.
- A green local gate is not a green CI. Both legs, on a real run.

## Two findings from the widening worth carrying forward

1. **A suppression can look live and be dead.** isort wrapped a long fallback import
   in parentheses and left its `# type: ignore` on the inner line, where mypy does not
   apply it. Nothing local surfaced it; mypy 2.3.1 in a CI-equivalent venv did. This is
   the repo's own defect class, found inside the repo.
2. **`ruff check --select X` overrides the config's select.** Measuring a family in
   isolation makes every suppression outside the override read as dead — the same tree
   reports 27 unused-noqa that way and 2 against the real gate. The kickoff's numbers
   were produced by exactly this error. Measure with a bare `ruff check`.

## The method that ended three failed release attempts

Do not trust the local venv. On v0.3.0 it was wrong in three directions at once: ruff
0.15.16 vs CI's 0.16.3, mypy 2.1.0 vs 2.3.1 (different error codes, so the ignore named
a code CI never emitted), and a stale editable dist-info reporting the previous version.

Build a CI-equivalent venv and verify there before pushing anything a release gate
judges. Both legs, since they differ:

```
python -m venv <tmp>/civenv                       # once per CI python: 3.11 AND 3.13
<tmp>/civenv/Scripts/python -m pip install -e ".[dev]" build
<tmp>/civenv/Scripts/python -m ruff --version      # confirm it matches CI's resolve
<tmp>/civenv/Scripts/python verify.py --installed
```

`uv python list --only-installed` has 3.11.15 and 3.13.13 on this rig.

## Fences

- `identity_subgate.py`: **no delete, no promote, no wire.** Thresholds 0.55 / 0.05 stay.
- Version **1.0.0** unless the Director says bump. (This fence read 0.3.0 through two
  releases — the defect class this repo prosecutes, in its own fence list. Keep it current.)
- **Do not run Phase 10 / publish / tag** unless asked.
- Do not lower a gate to make it green.
- No mutmut, no dependabot. Gates `raise`, never bare `assert`. ASCII in tool output.
- Cloud Comfy is the default generate path; local 5090 only if asked. The greened live
  generate already ran — do not re-run it to "confirm."
- GEPA stays offline, `[synth]`, never on the per-asset hot path. `pcraft compile` does
  not invent a pixel metric.
- Do not start InstantID rewrites or identity-sub-gate wiring as a "next obvious step."
  They are not.
- Do not pull `FLUX.1-dev` (24 GB gated) unless asked.
- Do not share a fixed `--basetemp` across seats. `verify.py` uses a fresh `mkdtemp`.
- Armature (`E:\AI\armature`) has foreign dirty index work. Leave it.
- Path rule on this rig: `F:/AI/...` in old memory means `E:/AI/...`. No F: or G: drive.

## Recommended next increment (Advisor ruling)

**Nothing on the board has a Director go.** Both prior items are closed and verified on
real runs. Two open items are written up in `HANDOFF.md` and both are **gated**:

1. **`verify.py` honesty** — declare the gate's scope in its output, add `--audit` as an
   opt-in leg, and add a version-coherence assertion under `--installed`. Audit-on-by-
   default is **rejected**: it makes the release gate time-varying and puts a network
   call in a hermetic gate. Needs a Director go.
2. **The stale `pcraft==0.1.0` dist in the blessed `.venv`** — half-repaired
   non-destructively (metadata now reports 0.3.0); clearing the leftover is a `pip
   uninstall`, which is a delete, so it needs a Director go.

If the Director does **not** name a job: measure HEAD, re-count, stop.

Still out, only if asked:

1. Local Flux text-only / Fill — weights are not on disk.
2. Point the per-asset loop at `DSPySynthesizer` + the GEPA pin.
3. Phase 10 full treatment / publish.

## Memory

The canonical store is `C:\Users\mikey\.claude\projects\F--AI\memory\`; index is
`MEMORY.md`. This repo's paste-ready brief:
`memory/prompt-craft-ci-311-audit-kickoff.md`. The consumed widening brief is
`memory/prompt-craft-ruff-widening-kickoff.md` (banner-stamped, do not re-run).
The **repo** files (`HANDOFF.md` / this file) win if the store drifts.
