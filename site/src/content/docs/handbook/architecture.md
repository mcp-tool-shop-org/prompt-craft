---
title: Architecture
description: The core/plugin boundary, what a domain plugin exports, and the test that keeps the claim honest.
sidebar:
  order: 4
---

The split is by **Parnas secret**: what stays the same across image, video and workflow lives in
`core/`; what changes per generator or verifier lives in a plugin.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
    contract/    typed contract, fail-closed loader, atoms → question DAG, provenance hash
    loop/        synth→generate→verify→retry→bind state machine; named compensators
    gate/        dependency-ordered harness, family guard, thresholds, exit contract
    synth/       prompt synthesis, the anti-prose-dump guard, pre-generation assert
    optimize/    offline compile; the pinned compiled artifact
    receipt/     replayable per-asset provenance record
  cli/           pcraft: synth | gate | bind | list | validate | demo | replay | doctor | schema | recipe | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, three verifier tiers, encoder rules, sprite subdomain
```

## What a plugin exports

Exactly three things:

- a **Generator**
- a list of **Verifiers**
- an **encoder ruleset**

Adding a new domain is a new sibling under `domains/`. Nothing in `core/` changes.

That last sentence is a claim, and claims in this repo are supposed to be checked rather than
asserted — so it was. An outside seat was asked to build a feature and, finding the plugin
contract genuinely unchanged, reported that the boundary holds *for a plugin-shaped feature*. It
also found the useful limit: a feature that is neither a generator nor a verifier is not
plugin-shaped, and forcing it through the boundary would mean adding a fourth secret. Knowing
where a boundary stops being useful is worth as much as knowing that it holds.

## What keeps it honest

`core/` imports **zero** diffusion or torch symbols, and there is a test asserting exactly that.
The consequence is that the entire core suite runs with a mock generator and verifier on any
machine — and **that GPU-free run is the proof the boundary holds**, not a convenience.

If someone reaches from `core/` into a plugin's dependency, the suite stops running on machines
without a GPU, and the failure is loud and immediate rather than discovered months later.

## Mutation-tested decision points

Coverage was 81% while four real defects sat inside code the suite executed — every one of them a
line that ran and asserted the wrong thing. Three shared one shape: a compound predicate whose
second clause silently overrode the first.

So the eleven compound predicates in `core/` are **mutation-tested**. A one-off harness flips each
one — drops a clause, inverts a comparison, swaps `and` for `or` — and records whether any test
notices. The first pass against a 77-test suite killed 8 mutants and **13 survived**. After the
fixtures that gap earned, 20 of 21 are killed, and the single survivor is documented rather than
hidden: it is defensive code whose mutation produces no behavioural change.

The harness lives in `scripts/`. It is deliberately **not** a CI dependency — a whole-repo mutator
spends most of its time on equivalent mutants and docstring noise, and the eleven sites were the
actual decision surface.

## Provenance

Every bound asset writes a replayable receipt pinning the contract hash, the compiled synthesizer
id, the generator id with seed and sampler, the verifier id and version, and the full per-atom
gate transcript. Fields that genuinely cannot be reached are recorded **absent with a reason**
rather than omitted or invented — a field that reads as filled when nobody can know it is worse
than a visible hole.
