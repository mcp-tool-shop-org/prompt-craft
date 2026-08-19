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

Six legs: **version coherence**, lint, typecheck, the suite, the suite again under `-O`, and a
package build.

The `-O` pass is not ceremony — `assert` is stripped under `-O`, so a check written as an
`assert` silently disappears in optimized mode. Every refusal in this codebase `raise`s, and
that second pass is what proves it.

**Version coherence** compares the installed distribution's version against the one
`pyproject.toml` declares, and refuses when they differ. An editable install's metadata is not
regenerated when `pyproject.toml` changes, and `package_version()` falls back to the tree's
literal *only* when the distribution is missing entirely — so stale metadata is *found* and the
wrong version is returned silently. That happened twice here. It runs first, because an
environment lying about its version should not be discovered after a full suite and two builds.

The gate also **lints and typechecks itself**. That sounds obvious and was not true until v0.4.0:
the legs covered `src` and `tests` and skipped the file defining them.

### What it does not check

The run closes by naming its own scope:

```
VERIFY OK -- checked: version coherence, lint, typecheck, suite, suite under -O, build
NOT CHECKED -- dependency audit. CI runs pip-audit as a separate step, so a green
verify.py is not yet a green CI.
```

A bare `OK` implies a scope this gate does not have. "Could not check" must never read as
"checked clean" — the same rule the CI workflow applies to its own skipped entries.

### The dependency audit, opt-in

```bash
python verify.py --installed --audit
```

Off by default, and not out of squeamishness about the network: running it makes the gate
**time-varying**, so an unchanged tree passes today and fails tomorrow when an advisory
publishes. That is right for CI and wrong for a release gate.

It reports three outcomes rather than two, because two would have shipped a gate that is red
forever:

| outcome | behaviour |
|---|---|
| advisory **with** a published fix | **fails** — there is a move available |
| advisory with **no** published fix | reported, does not fail |
| **could not audit at all** | reported loudest |

The third row is the one that would otherwise pass silently. With `[image]` installed, `torch`
is a local CUDA build that is not on PyPI, so the auditor cannot see the largest dependency in
the tree at all — and a report saying "no vulnerabilities" would be printing "could not check"
as "checked clean". Every run also names the **extras it resolved against**, because the verdict
depends on that set: `[synth]` surfaces an advisory `[dev]` does not. A passing run carrying any
caveat prints `QUALIFIED` rather than a bare OK.
