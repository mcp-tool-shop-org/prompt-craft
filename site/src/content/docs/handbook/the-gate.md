---
title: The gate
description: Three tiers, four exit codes, a different-family verifier, and why "could not check" is its own answer.
sidebar:
  order: 3
---

The gate reads the rendered pixels and asks the contract's claims of them, one at a time. Its
job is to be **able to fail** — a check that cannot fail is not a check, and most of this page is
about the ways that goes wrong.

## Three tiers, cheapest deciding first

| Tier | Decides |
|---|---|
| 0 | closed-set and presence claims — a palette, a garment, a silhouette |
| 1 | compositional claims, and a whole-contract screen |
| 2 | localizes *which* claim failed when tier 1 fails or is borderline |

Escalation happens only when a cheap answer is unclear, so the expensive tier runs on the cases
that need it rather than on everything.

Tier-2 is a **Davidsonian Scene Graph** expansion (Cho et al. 2024): the failed atom becomes
entity / attribute / relation yes-no probes. A missing entity skips dependents. The default QG
is a GPU-free template; inject `qg=` to swap it. The answerer may still be Tier-1's VQAScore
weights — that sharing is on `shares_model_with`, not hidden behind the `dsg-qg` family label.

When the loop escalates to a human, the reason is a **contrastive checkpoint**: what you probably
thought, and what the gate chose, per flagged atom. A bound run has none.

**CLIPScore is not used as the gate metric.** It behaves as a bag of concepts — blind to which
attribute belongs to which object, to counts, and to relations. Recent work confirms this is a
property of the training data rather than something fixable by scaling or by adding hard
negatives. It is documented as known-broken in the verifier interface so nobody reintroduces it.

## The verifier is a different family from the generator

A guard refuses to run when the generator and verifier normalize to the same model family. Same
weights are a special case; sibling checkpoints count as the same family too.

Stated precisely, because the slogan and the enforced rule are not identical: what the code
enforces is **family inequality**, not a ban on any particular kind of model. A generative
vision-language model scoring the output of a diffusion model is a different family and passes
the guard. Two generative VLMs checking each other do not.

The evidence for the underlying principle is **convergent rather than direct**. Discriminative
yes/no polling is measurably more stable than open-ended captioning; models cannot reliably
self-correct without external feedback; a model's ability to recognize its own output tracks its
preference for that output; and vision-language models will report near-total confidence on
content they hallucinated. No single study runs the exact head-to-head. The rule is sound and
cheap; it is not a measured law, and this handbook will not pretend otherwise.

## Four exit codes, because there are four outcomes

| exit | meaning |
|---|---|
| `0` | the gate ran and every required atom passed |
| `1` | bad arguments or a malformed contract |
| `2` | it ran, and a required atom **failed** |
| `3` | it ran, and the result is **unconfirmed** — the human band |
| `4` | it **could not run** |

The split between `2` and `4` is the important one. **"I could not check" and "I checked and it
is bad" are different facts**, and merging them causes real harm in both directions:

- Browsers deliberately *soft*-fail certificate revocation, because hard-failing turned every
  certificate-authority outage into a global outage — and the root cause named in that history is
  exactly this conflation.
- Monitoring standards have carried a distinct **UNKNOWN** verdict since the 1990s, separate from
  CRITICAL, for the same reason.

This gate got it wrong first. Given a path that did not exist it marked every atom SKIPPED — its
verifiers reported themselves unavailable before anything touched the path — printed a verdict,
and **exited 0**. It reported on an image it never opened.

## The tier census — who watches the watcher

Every transcript carries **how many required tiers actually executed**, independently of the
verdict. A pass with one of two tiers run is a pass whose cheap screen never happened, and it
says so.

The argument for this is not theoretical. Verification tooling used on this very project
produced a confident top-level verdict while every one of its checks was failing against an
unreachable provider — the headline read like a judgment about the work. A positive
"N of M executed" signal is the difference between a quiet no-op and a visible one.

## What the gate does not do

It does not judge whether the figure is *the right character*. That is a human judgment, and no
metric here approximates it — identity metrics are documented as mistaking a change of texture or
colour palette for a change of identity, which makes them actively misleading for exactly the
question people want to ask of them.

The gate checks that named, depictable claims are present or absent. That is a narrower question,
and an answerable one.
