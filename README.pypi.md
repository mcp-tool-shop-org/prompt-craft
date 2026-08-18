# prompt-crafter

**Say what the picture must contain. Check that it does. Refuse when it doesn't.**

A generative image pipeline will happily hand you a hero with the wrong face, the wrong palette
and none of the faction's markings — and report success, because nothing looked. prompt-crafter
replaces the opaque prose prompt with a **typed contract of depictable claims**, uses that same
list twice — once to write the prompt, once to check the pixels — and **blocks the asset when a
required claim is not there**.

**The one idea:** the contract's atom list is *the same list used twice.* Writing the prompt and
checking the result read from one source, so the thing you asked for is the thing that gets
verified. That is what closes the loop an opaque prompt leaves open.

## Install

```bash
pip install prompt-crafter
pcraft --help
```

The distribution is `prompt-crafter`; the import package and the command are `pcraft`. Requires
Python 3.11+. The core's only runtime dependency is `pydantic`.

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft list              # contract ids in the store
pcraft validate          # resolve + compile the question DAG, no generate
pcraft gate <image>      # check an image against a contract
pcraft recipe            # emit the Cloud Kontext + fist-only Fill graph
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## What a contract looks like

Not a prose prompt. A list of **atomic, depictable, individually checkable** claims:

- **`must_have`** — a garment, a palette, a silhouette, a sigil. Each names which gate tier
  verifies it, a severity, and optionally a `depends_on` edge, so there is no point verifying the
  colour of an axe that is not there.
- **`must_not`** — anti-constraints, verified as **absence on the pixels**. Not a negative prompt:
  negative prompts leave residual features and fall to paraphrase.
- **`identity_ref`** — a reference plate. **Identity is conditioning, not tokens.** Anatomical
  text makes a diffusion model render a specimen; a reference image binds the specific face.

Contracts inherit — a character extends a faction — and inheritance is **fail-closed**: a child
may raise a requirement, never relax or silently drop one it inherited.

## The exit code is the point

| exit | meaning |
|---|---|
| `0` | the gate ran and every required atom passed |
| `1` | bad arguments or a malformed contract |
| `2` | it ran, and a required atom **failed** |
| `3` | it ran, and the result is **unconfirmed** — the human band |
| `4` | it **could not run** |

The `2` / `4` split is the whole design. **"I could not check" and "I checked and it is bad" are
different facts.** Merging them is why browsers soft-fail certificate revocation, and why
monitoring standards have carried a distinct *unknown* verdict since the 1990s. Every gate
transcript also reports how many required tiers actually executed, so a gate that quietly stopped
checking cannot read as a pass.

The verifier is always a **different model family from the generator**, enforced by a guard that
refuses to run otherwise. CLIPScore is not used as the gate metric — it behaves as a bag of
concepts, blind to which attribute belongs to which object.

## Honest status

**v0.2.1 — the core is real. SDXL conditioning is assembled in code. A local 5090 `generate()` has now been run. One Cloud recipe has been run live.**

- **328 tests passing** (counted 2026-08-18), GPU-free and deterministic. The whole suite runs
  against a mock generator and verifier, which is what proves the plugin boundary holds.
- Flux Fill inpaint is wired. `method=reference` writes the Cloud recipe (`GATE_CLOUD_SUBMIT`).
  ControlNet pose and IP-Adapter stay refused on Flux.
- The eleven compound decision points in the core are **mutation-tested** — 20 of 21 mutants
  killed, and the survivor is named rather than hidden.
- SDXL ControlNet OpenPose, IP-Adapter, LoRA, **InstantID**, and regional inpaint are
  **wired and covered by fake-torch tests**. InstantID and IP-Adapter cannot share one
  generate. Local `generate()` **ran** on the 5090 (2026-08-18, seed `169405236028824`).
  The frame is orcish; grip, sigil, and bracer did not land. Two IP-Adapter plates on
  one adapter refuse before pixels. Flux refuses those identity methods.
- `pcraft recipe` emits the Cloud Kontext stitch + left crop + fist-only Fill graph. A live
  Cloud submit (2026-08-18) produced a single-panel crop and kept the bracer.
- Tier-2 is a real DSG expansion. Escalation is a contrastive checkpoint. A live GEPA
  compile ran 2026-08-18 on local Ollama `hermes3:8b` (600B was not up). Pinned
  `sprite.synth.v1-gepa.json`. The seed artifact is untouched. The per-asset loop
  still uses `TemplateSynthesizer`.
- The identity sub-gate is **not wired**. Its thresholds have no holdout.
- Pre-1.0 deliberately, and a test enforces it. Promotion should follow evidence, not a version
  bump.

## Trust

No credentials are read, stored or transmitted. **No telemetry** — there is no opt-out because
there is nothing to opt out of. The core imports no networking library at all; the optional
extras reach a model host by their nature, and installing them is a choice. File operations are
**not sandboxed**: `--records-dir` and `--db` write where you point them, deliberately, for a
local-first tool.

Deliberate refusals carry a code, a message and a hint, and **raise rather than `assert`** — so
`-O` cannot delete them, and the suite runs a second time under `-O` to prove it.

---

**[Documentation and handbook →](https://mcp-tool-shop-org.github.io/prompt-craft/)**
· [Source](https://github.com/mcp-tool-shop-org/prompt-craft)
· [Changelog](https://github.com/mcp-tool-shop-org/prompt-craft/blob/main/CHANGELOG.md)

MIT
