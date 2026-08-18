---
title: The CLI
description: Every pcraft command, what it will do, and what it will refuse.
sidebar:
  order: 6
---

Measured against `pcraft --help` on 2026-08-18. Flags that do not appear here do not exist.

## GPU-free doors

| command | what it does |
|---|---|
| `pcraft demo` | synth → generate → gate → repair → bind on the shipped example, stub generator, scripted scores |
| `pcraft list` | print contract ids. `--contracts-dir` is the public store door |
| `pcraft validate` | resolve + compile the question DAG. No generate, no gate |
| `pcraft synth` | template synthesizer. Every token traces to an atom |
| `pcraft gate <image>` | score an image against a contract. Missing path is exit 4, not a failed atom |
| `pcraft bind` | the full loop. `--mock` is the GPU-free path; scores are scripted constants |
| `pcraft replay <record>` | reconstruct the question DAG and refuse on drift |
| `pcraft doctor` | python, extras, store load. Reports `pcraft 0.2.1` |
| `pcraft schema` | JSON Schema for the authoring contract |
| `pcraft --json` | on the dumpable commands, the pydantic model is stdout |

An empty custom `--contracts-dir` is `INPUT_EMPTY_STORE` (exit 1), never a silent fall-back to
the shipped ashen-reaver demo.

## Cloud / offline doors

| command | what it does |
|---|---|
| `pcraft recipe` | write the Kontext stitch + in-graph left crop + fist-only Fill graph. Does **not** submit. `--image-name local=cloud` remaps uploaded plates. `hands` / `weapon` refuse — they ate the bracer |
| `pcraft compile --seed` | pin the scaffold synthesizer artifact |
| `pcraft compile` | needs `[synth]` and a Python `gate_metric`. The CLI does not generate pixels (`STATE_COMPILE_NEEDS_GATE`) |
| `pcraft sync-rules` | regenerate encoder-craft rules from the readouts database |

## What the CLI will not do

- It will not silently become ashen-reaver when you point it at an empty store.
- It will not submit a Cloud job. `recipe` writes JSON.
- It will not run a live GEPA search. That is `compile_synthesizer(...)` from Python, offline.
- It will not wire the identity sub-gate. That module is measured, not promoted.
