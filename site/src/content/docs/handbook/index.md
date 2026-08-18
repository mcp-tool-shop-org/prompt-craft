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
| The core | **205 tests passing**, GPU-free and deterministic — it runs anywhere, against a mock generator and verifier |
| The plugin boundary | `core/` imports zero diffusion or torch symbols. The GPU-free suite is the proof, not the claim |
| Decision points | the eleven compound predicates in `core/` are **mutation-tested** — 20 of 21 mutants killed, the survivor named |
| The GPU path | **has never executed on any machine here.** `bind --no-mock` refuses with a missing-dependency error |
| Conditioning | the loop assembles `pose_refs` and `identity_refs` and writes them on the receipt. Neither shipped generator reads a key of that dict. If those refs are present, `generate()` refuses. Pose-lock and identity-binding are unimplemented, not merely unexercised |
| Sub-gate thresholds | **hardcoded defaults with no calibration** — no holdout, no citation. Placeholders, and labelled as such |
| Real canon | the shipped contract is a **generic invention**. Binding real project canon is a deliberate human decision, not a default |

Three claims earlier versions of this project made, corrected here rather than quietly dropped:

- The three-zone thresholds were described as *calibrated against a human-labelled holdout*. They
  were not, and are not. They are defaults.
- The rule that a generative model is never its own gate was written as though a study had
  established it. The real evidence is **convergent, not direct**: discriminative yes/no polling
  is measurably more stable than open-ended captioning, models cannot reliably self-correct
  without external feedback, and a model's self-recognition tracks its self-preference bias. No
  single study runs the head-to-head. The rule is sound. The certainty was overstated.
- Everything below the plugin boundary was described as *unproven by measurement*. That
  understated the generators: conditioning is unread. The path is unimplemented, not untested.

## Where to go next

- **[Getting started](./getting-started/)** — install, and run the whole loop with no GPU
- **[Contracts](./contracts/)** — what a contract is made of, and why absence is its own problem
- **[The gate](./the-gate/)** — three tiers, four exit codes, and why "could not check" is its own answer
- **[Architecture](./architecture/)** — the core/plugin boundary and what keeps it honest
- **[Security](./security/)** — what this tool touches, what it does not, and the sharp edge
