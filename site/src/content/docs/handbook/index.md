---
title: The prompt-craft handbook
description: What prompt-craft is, the one idea it rests on, and an honest account of what it has and has not proven.
sidebar:
  order: 0
---

**Say what the picture must contain. Check that it does. Refuse when it doesn't.**

A generative image pipeline will happily hand you a hero with the wrong face, the wrong palette
and none of the faction's markings — and report success, because nothing looked. That is not a
model failure. It is a missing contract: the prompt was prose, and prose cannot be checked.

## The one idea

The contract's atom list is **the same list used twice** — once to write the prompt, once to
check the pixels.

That single fact is the whole design. Writing and verifying read from one source, so the thing
you asked for is the thing that gets verified, and a claim cannot quietly go missing between the
two. Everything else in this handbook follows from it.

```
   CONTRACT  ──atoms──▶  SYNTHESIZE  ──prompt──▶  GENERATE
   typed, depictable     every token traces      diffusion + control
        │                to an atom                     │
        │ the same atoms                                │ pixels
        └──────────────────────▶  GATE  ◀───────────────┘
                    a DIFFERENT model family checks the
                    contract against the image
                         │                    │
                       PASS                FAIL / UNCERTAIN
                         ▼                    ▼
                    BIND to canon      REPAIR ladder, or a
                                       human checkpoint
```

## What is honestly true today

This handbook exists partly to stop the project overselling itself, so the limits come before
the features.

| | |
|---|---|
| The core | **328 tests passing** (counted 2026-08-18), GPU-free and deterministic — it runs anywhere, against a mock generator and verifier |
| The plugin boundary | `core/` imports zero diffusion or torch symbols. The GPU-free suite is the proof, not the claim |
| Decision points | the eleven compound predicates in `core/` are **mutation-tested** — 20 of 21 mutants killed, the survivor named |
| SDXL conditioning | ControlNet OpenPose, IP-Adapter, LoRA, **InstantID**, and regional inpaint are **wired and fake-torch tested**. InstantID and IP-Adapter cannot share one generate. Local `generate()` **ran** on the 5090 (2026-08-18, seed `169405236028824`). The frame is orcish; grip, sigil, and bracer did not land |
| Flux encoder | Fill inpaint is wired. Pose / IP-Adapter / LoRA / InstantID stay refused. `method=reference` writes the Cloud recipe and will not pretend Kontext ran locally |
| Cloud recipe | `pcraft recipe` emits Kontext stitch + left crop + fist-only Fill. A live Cloud submit (job `06668d4c`) produced a single-panel crop and kept the bracer |
| Gate / synth | Tier-2 is a real DSG expansion. Escalation is a contrastive checkpoint. A live GEPA compile ran 2026-08-18 on local Ollama `hermes3:8b` (not 600B). Pinned `sprite.synth.v1-gepa.json`. The per-asset loop still uses `TemplateSynthesizer` |
| Identity sub-gate | **not wired** into `orchestrate`. Thresholds 0.55 / 0.05 have no holdout |
| Real canon | the shipped contract is a **generic invention**. Binding real project canon is a deliberate human decision, not a default |

Three claims earlier versions of this project made, corrected here rather than quietly dropped:

- The three-zone thresholds were described as *calibrated against a human-labelled holdout*. They
  were not, and are not. They are defaults.
- The rule that a generative model is never its own gate was written as though a study had
  established it. The real evidence is **convergent, not direct**: discriminative yes/no polling
  is measurably more stable than open-ended captioning, models cannot reliably self-correct
  without external feedback, and a model's self-recognition tracks its self-preference bias. No
  single study runs the head-to-head. The rule is sound. The certainty was overstated.
- Conditioning was described as unread. SDXL now reads the assembled refs in code. A live local
  `generate()` on this machine has now been run. Wired-and-applied is not the plate landing.

## Where to go next

- **[Getting started](./getting-started/)** — install, and run the whole loop with no GPU
- **[Contracts](./contracts/)** — what a contract is made of, and why absence is its own problem
- **[The gate](./the-gate/)** — three tiers, four exit codes, and why "could not check" is its own answer
- **[The CLI](./cli/)** — every command, what it will and will not do
- **[Architecture](./architecture/)** — the core/plugin boundary and what keeps it honest
- **[Security](./security/)** — what this tool touches, what it does not, and the sharp edge
