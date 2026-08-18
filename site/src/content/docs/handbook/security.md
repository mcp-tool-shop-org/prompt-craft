---
title: Security
description: What prompt-craft touches, what it does not, the one sharp edge, and how refusals are built so they cannot be optimized away.
sidebar:
  order: 5
---

Measured against the tree rather than asserted. Where something is a deliberate trade-off it is
disclosed as one instead of being claimed away.

## Data touched

- **Contract JSON** you point it at.
- **Images** you pass to the gate.
- **Provenance records** written under the directory you name (`--records-dir`).
- A **recipe database**, read-only, when you run `sync-rules`.

Nothing else is read.

## Data not touched

- **No credentials of any kind** are read, stored or transmitted.
- **No telemetry, analytics or usage counting.** There is no opt-out because there is nothing to
  opt out of.
- **No network egress from the core** — it imports no networking library at all.

The optional `[image]` and `[synth]` extras reach a model host by their nature. That is the only
network path in the project, and installing those extras is a deliberate choice.

## Permissions

Ordinary user permissions. No elevation, no service installation, no registry or system-settings
writes.

## The sharp edge

**File operations are not sandboxed.** `--records-dir` and `--db` write wherever you point them.

This is deliberate for a local-first CLI — the operator names the path, and constraining it to a
blessed directory would make the tool worse at the thing it is for. It is listed here rather than
quietly omitted, because a disclosed trade-off is a decision and an undisclosed one is a
surprise. Point those flags somewhere you intend.

## Errors and refusals

**Deliberate refusals carry a structured shape** — a code, a message, and a hint — and they
**`raise`; they are never an `assert`.**

That distinction is load-bearing. Python's `-O` flag strips `assert` statements entirely, so a
safety check written as an assertion silently disappears in optimized mode: the code still reads
as though it is guarded, and nothing guards it. Every refusal here raises, and the verify script
runs the whole suite a **second time under `-O`** specifically to prove the refusals still fire.

Unexpected failures print a traceback only under `--debug`. A schema-invalid record used to dump a
raw pydantic traceback to anyone who mistyped a path; it now carries a structured error.

## What the gate will not claim

The gate can tell you whether named, depictable claims are present or absent on an image. It
**cannot** tell you whether the figure is the right character, and it does not try.

Identity metrics are documented as mistaking a change in texture or colour palette for a change in
identity, and face detectors trained on photographs frequently fail to fire at all on stylized
subjects — returning a confident number about a face they never found. A metric that reports the
same value when it is working perfectly and when it is doing nothing is not measuring anything.
That question stays with a person.

## Reporting

Security reports go through the process in
[SECURITY.md](https://github.com/mcp-tool-shop-org/prompt-craft/blob/main/SECURITY.md) in the
repository.

## Support status

`main` is the only supported state. No release channel, no backport policy, no SLA. This is studio
infrastructure published in the open, not a product with a support contract.
