---
title: Contracts
description: What a contract is made of, why absence is its own problem, and how inheritance fails closed.
sidebar:
  order: 2
---

A contract is not a prompt. It is a list of **atomic, depictable, individually checkable**
claims — and because each one is separately checkable, the pipeline can tell you *which* claim
went missing rather than that the image "looks wrong".

## The three parts

### `must_have` — claims that must be present

Each atom carries an id, a claim phrased as something you could point at, a `check_type` naming
which gate tier verifies it, a `severity`, and optionally a `depends_on` edge.

That edge matters more than it looks. A dependency-ordered gate marks a claim **N/A** when its
parent did not pass, so you never get a confident verdict on the colour of an axe that is not in
the picture. Without it, a failed parent produces a cascade of meaningless child scores that
average out into a passing grade.

### `must_not` — anti-constraints, verified on the pixels

An anti-constraint is **not** a negative prompt. Negative prompts leave residual features and
fall over to paraphrase; asking for "no shield" does not establish that no shield is present.
Satisfaction requires the gate to confirm **absence** on the actual output.

**Absence is a harder capability than presence, and prompt-craft says so in the type system.**
`MustNot` carries its own `severity`, because a negation's blocking power should match the
evidence behind the check enforcing it. CLIP-family encoders are documented as limited at
negation, and no published work benchmarks a sigmoid zero-shot score as an absence verifier at
all. So a negation whose verifier is not calibrated for absence is marked `optional`: it still
runs, still scores, still rides the transcript — it simply does not claim the certainty required
to block a bind.

The shipped example contract declares all four of its negations `optional` for exactly that
reason. Raising one to `required` is the correct move *after* someone measures a verifier on
absence, not before.

### `identity_ref` — the reference plate

**Identity is conditioning, not tokens.** Anatomical description makes a diffusion model render
*a specimen of a type*; it cannot specify a particular face. A reference plate bound through
an adapter can. The text describes what is nameable; the plate carries what is not.

`method` names the encoder:

- `ip_adapter` — SDXL IP-Adapter (wired; local generate unexercised)
- `reference` — the Cloud Kontext stitch + left crop + fist-only Fill recipe (`pcraft recipe`). On the Flux generator this writes the graph and raises `GATE_CLOUD_SUBMIT` rather than pretending Kontext ran locally.
- `lora` / `instantid` — still refuse
- `none` — skip the plate

A `MustNot` may carry `spatial` the same way a `must_have` can. Inherited spatial is frozen.

## Inheritance fails closed

A character contract `extends` a faction contract. The merge rule is one-directional:

- A child may **raise** a requirement — take an inherited `optional` atom to `required`.
- A child may **add** atoms of its own.
- A child may **never relax** an inherited requirement, and never silently drop one. An atom the
  child does not mention survives from the base.

Attempting to relax raises `CONTRACT_RELAXATION` and names both severities. This holds for
anti-constraints as well as positive claims — if a faction forbids firearms as a blocking rule,
no character contract can quietly demote that to a warning.

## Why "a hole is a row"

When a surface or an element has nothing assigned to it, the contract records it as an explicit
empty slot rather than leaving it out. An element list cannot show you what it forgot: a missing
entry and a deliberate absence look identical in a list of things that are present. Making the
hole a row is what lets anything downstream — a person, a check, a diff — see the gap.
