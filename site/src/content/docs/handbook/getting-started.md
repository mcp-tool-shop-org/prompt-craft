---
title: Getting started
description: Install prompt-craft, run the whole loop without a GPU, and read the exit code it gives you.
sidebar:
  order: 1
---

The core is **GPU-free**. The entire loop — synthesize, generate, gate, repair, bind — runs
against deterministic stubs on any machine, and the whole test suite executes that way. That is
not a demo mode bolted on afterwards; it is what proves the plugin boundary actually holds.

## Install

```bash
pip install prompt-crafter
pcraft --help
```

Or as a Node launcher that forwards to the same Python and inherits its exit code:

```bash
npm install -g @mcptoolshop/prompt-crafter
```

The distribution is **`prompt-crafter`** — `pcraft` and `prompt-craft` are both taken on PyPI —
while the import package and the command stay `pcraft`. For development from a clone:

```bash
python -m venv .venv
. .venv/Scripts/activate      # POSIX: source .venv/bin/activate
pip install -e ".[dev]"
```

Requires **Python 3.11+**. CI runs 3.11 and 3.13 on the core + `[dev]`.
The `[image]` extra is not claimed on 3.11. The core's only runtime
dependency is `pydantic`.

## Run the loop

```bash
pcraft demo
pcraft list
pcraft validate
pcraft doctor
```

`demo` runs synth → generate → gate → repair → bind end to end with a stub generator and a
scripted verifier, and writes a provenance receipt. `list` and `validate` open a contract store
without generating. `doctor` reports python, extras, and whether the store loads. No GPU, no
network, no model downloads. `--contracts-dir` points at a tree that is not the shipped demo.

## Check an image

```bash
pcraft gate hero.png
```

**Read the exit code, not just the text.** The human-readable transcript and the process exit are
different objects on purpose:

| exit | meaning |
|---|---|
| `0` | the gate ran and every required atom passed |
| `1` | bad arguments, or a contract that does not parse |
| `2` | it ran, and a required atom **failed** |
| `3` | it ran, and the result is **unconfirmed** — the human band |
| `4` | it **could not run** — unreadable input, or no required tier available |

If you script anything around this tool, branch on `4` separately. "I could not check" is not a
pass and it is not a failure, and treating it as either is how a gate becomes decorative.

## Read what was bound

```bash
pcraft replay records/hero.json
```

Every bound asset writes a replayable receipt pinning the contract hash, the compiled synthesizer
id, the generator id with its seed and sampler, the verifier id and version, and the full
per-atom gate transcript.

## The optional extras

```bash
pip install -e ".[image]"    # torch / diffusers — the real generator and verifiers
pip install -e ".[synth]"    # DSPy + a hosted LM — the real synthesizer
```

**Neither is needed to run, test, or evaluate the core.** Local `generate()` on a 5090 **has**
been run here (2026-08-18, ashen-reaver, OpenPose + identity plate). The frame is orcish;
grip, sigil, and bracer did not land. A Cloud recipe (`pcraft recipe`) **has** been submitted
live (2026-08-18). A live GEPA compile ran 2026-08-18 on local Ollama `hermes3:8b`
(not 600B) via `compile_synthesizer` and an external `gate_metric`. The CLI will
not invent one (`STATE_COMPILE_NEEDS_GATE`). `bind --no-mock` is the live
door when `[image]` is installed; missing extras are `DEP_IMAGE_MISSING`.
`--mock` stays the GPU-free scaffold.

## Verify a change

```bash
python verify.py --installed
```

One command: the suite, the suite again under `-O`, and a package build. The `-O` pass is not
ceremony — `assert` is stripped under `-O`, so a check written as an `assert` silently disappears
in optimized mode. Every refusal in this codebase `raise`s, and that second pass is what proves
it.
