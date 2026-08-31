# Stability — what semver covers, and what it does not

**As of v1.0.0.** This document is the promise. If something is not named here, it is not
covered, and you should not build on it without saying so out loud.

A `1.0.0` here is a claim about **interfaces**, not about pictures. The image pipeline has
capability gaps and the README's honest-status table lists them without softening. Those gaps
are not what a major version is about: they get better in **minor** releases. What `1.0.0`
says is that the things below stop moving under you without a major bump.

Every name in this file is checked by `tests/test_stability_surface_names_resolve.py`. A
document that lists an interface it no longer has is the exact defect this project exists to
catch, so it is not left to good intentions.

---

## Covered — breaking these requires a major version

### 1. CLI commands and their exit codes

| command | promise |
|---|---|
| `pcraft synth` | flags and stdout shape |
| `pcraft gate` | flags, `--json` transcript shape, exit codes |
| `pcraft bind` | flags, `--mock` / `--no-mock` behaviour, the receipt it writes |
| `pcraft list` | flags and stdout shape |
| `pcraft validate` | flags and refusal codes |
| `pcraft demo` | that it runs GPU-free end to end |
| `pcraft replay` | flags and drift refusals |
| `pcraft doctor` | flags and report shape |
| `pcraft schema` | the emitted JSON schema |
| `pcraft recipe` | flags and the emitted recipe graph |

**The exit-code contract is covered**, and it is the part most likely to be scripted:

```
0  success            1  user error (INPUT_/CONFIG_/CONTRACT_, and IO_RECORD_SCHEMA_UNSUPPORTED)
2  runtime error      3  partial — required atom unconfirmed (PARTIAL_)
4  could not run      (GATE_UNAVAILABLE, IO_GATE_INPUT)
```

`IO_RECORD_SCHEMA_UNSUPPORTED` is a deliberate per-code override: despite its `IO_` prefix it
exits **1**, matching its contract sibling `CONTRACT_SCHEMA_UNSUPPORTED` — a well-formed receipt
written by a newer prompt-craft is your input to upgrade for, not a tool crash. (v1.0.0 as
tagged exits 2 here; the alignment landed on `main` immediately after and ships in the
first release that actually reaches the registries -- v1.0.0 was tagged but its publish
was never approved, so no registry artifact carries the old behaviour.)

`4` is deliberate and load-bearing: **could-not-check is not checked-clean**, and collapsing it
onto `2` would let a CI branch read "the gate ran and failed" when the gate never ran.

An **interrupt is outside this table by convention, not by omission**: a bare Ctrl-C exits
`130` (128 + SIGINT), the universal shell convention, surfaced by the CLI framework before any
command body runs. It is pinned by a test and will not be folded into the codes above — a
scripted caller should treat it as "the operator stopped this", which no gate verdict can
mean — folding it into exit 1 would leave a script unable to tell a typo from an interrupt.

Error **codes** are covered — a code will not be renamed or have its meaning changed under a
minor. Error **message wording** and hint text are not; parse the code, not the prose.

### 2. Import paths

| module | promise |
|---|---|
| `pcraft.package_version` | callable, returns the distribution version |
| `pcraft.errors` | `PromptCraftError`, its `code` / `message` / `hint` shape, `exit_code_for` |
| `pcraft.testing` | the mock generator and verifier used to run the loop GPU-free |
| `pcraft.sample` | `load_sprite_example`, `load_store`, `load_workspace`, `run_mock_loop` |
| `pcraft.core.contract.schema` | `Contract`, `ResolvedContract`, `Atom`, `MustNot`, `Severity`, `CheckType` |
| `pcraft.core.receipt.asset_record` | `AssetRecord`, `load`, `persist`, `replay` |
| `pcraft.core.gate.harness` | `GateTranscript` and the `Verifier` protocol |
| `pcraft.core.loop.retry_policy` | `Verdict`, `OutcomeClass`, `RepairAction`, `Attempt` |
| `pcraft.core.plugin` | the domain-plugin registration interface |

`pcraft.core` stays free of diffusion and torch symbols. That is a covered property, not an
implementation detail — `tests/test_core_is_gpu_free.py` is its proof.

### 3. On-disk formats

| format | version marker | promise |
|---|---|---|
| contract JSON | `$schema: prompt-craft/contract.v1` | a `contract.v1` file keeps loading |
| receipt JSON | `schema_version: "1"` | a `"1"` receipt keeps loading, and `replay` keeps reading it |

Both markers are **enforced**, as of v1.0.0. A contract declaring an unsupported `$schema` is
refused with `CONTRACT_SCHEMA_UNSUPPORTED`; a receipt declaring an unsupported
`schema_version` is refused with `IO_RECORD_SCHEMA_UNSUPPORTED` — which is a *different* answer
from `IO_RECORD_INVALID`, because "written by a newer prompt-craft" is not "corrupt" and must
not send you off re-binding a perfectly good file.

A receipt with **no** `schema_version` is read as v1. That is how every receipt written before
1.0.0 keeps working.

---

## Not covered — these may change in a minor release

Named explicitly, because "not mentioned" is how a promise gets assumed.

### Threshold *table values*

The bands in `sprite.calibration.json` (`sprite.cal.v1`) are **data, not interface**. They are
defaults and they will be retuned. Retuning them is not a breaking change.

What *is* covered: the table is versioned, and every receipt now stamps **both** that version
and a content hash of the band values themselves; `pcraft replay` **asserts both** — so a
decision made under one table cannot be silently replayed under another, *including* when the
values were retuned without touching the version string (that gap was real: measured, a value
retune under an unchanged version flipped a verdict while replay stayed silent — closed in the
first patch after v1.0.0). Receipts written before the hash existed replay under the version
check alone. You are protected from the drift being invisible, not from the drift.

### The identity sub-gate — provisional, and out of scope

`pcraft.domains.image.subdomains.sprite.identity_subgate` is **not covered by any part of
this promise.** It is measured, and it is **not wired into `orchestrate`** — it gates nothing
today.

Its thresholds `0.55` and `0.05` are **unvalidated defaults**. They were never calibrated
against a human-labelled holdout, they are bare constructor arguments in no table and no
receipt, and they may change or be removed entirely without a major version. Do not build on
this module, do not import it, and do not read its numbers as a tuned configuration.

Wiring it is a future decision that will need a holdout first. That work belongs before it is
*wired*, not before the package is *stable* — which is precisely why it can be excluded here
rather than blocking 1.0.0.

### `pcraft.core.optimize`

The offline GEPA compile path (`compile_synthesizer`, the compiled-artifact format) is
experimental. It requires the `[synth]` extra, it never runs on the per-asset hot path, and its
artifact layout may change in a minor. `pcraft compile` will not invent a pixel metric — that
refusal *is* stable — but nothing else here is.

### Everything under `pcraft.domains.image.subdomains.sprite`

The shipped sprite example is a **demonstration**, not an API. Its contract is a generic
invention rather than any real project's canon. Its layout, ids, and calibration file may move.

### Also not covered

- Python API **internals** — anything not listed under "Import paths" above, including every
  private name (leading underscore) and every module under `pcraft.domains`.
- **Log and human-readable output** wording. Parse `--json`, not the banner.
- The **npm launcher's** internals. Its CLI surface is `pcraft`'s.
- The **suite count**, `verify.py` leg list, and anything else about how the project checks
  itself. Those are ours to change.

---

## What a version number means here

- **major** — something in "Covered" broke.
- **minor** — new capability, new commands, retuned thresholds, better pictures.
- **patch** — fixes that break nothing above.

Pre-1.0 the standing ruling was *"a generate that ran is not a stability claim."* That was the
right answer for the wrong reason: it argued from capability, and capability is exactly the
category that does **not** block a stable interface. The blockers were an unversioned receipt
format, an inert `$schema` label, and a threshold version that was stamped and never asserted.
All three are closed above, which is why this document can exist.
