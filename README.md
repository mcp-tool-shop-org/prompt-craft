<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="docs/assets/logo.png" alt="prompt-craft" width="820">
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/prompt-craft/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/prompt-craft/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
</p>

#

**Say what the picture must contain. Check that it does. Refuse when it doesn't.**

A generative image pipeline will happily hand you a hero with the wrong face, the wrong palette
and none of the faction's markings — and report success, because nothing looked. prompt-craft
replaces the opaque prose prompt with a **typed contract of depictable claims**, uses that same
list twice — once to write the prompt, once to check the pixels — and **blocks the asset when a
required claim is not there**.

```
   CONTRACT  ──atoms──▶  SYNTHESIZE  ──prompt──▶  GENERATE
   typed, depictable     every token traces      diffusion + control
        │                to an atom                     │
        │ the same atoms                                │ pixels
        └──────────────────────▶  GATE  ◀───────────────┘
                    a DIFFERENT model family checks the
                    contract against the image, cheapest
                    tier deciding first
                         │                    │
                       PASS                FAIL / UNCERTAIN
                         ▼                    ▼
                    BIND to canon      REPAIR ladder, or a
                  (only when every     human checkpoint when
                   required atom       the gate is unsure
                   actually passed)
```

**The one idea:** the contract's atom list is *the same list used twice.* Writing the prompt and
checking the result read from one source, so the thing you asked for is the thing that gets
verified. That is what closes the loop an opaque prompt leaves open.

## Install

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

The distribution is **`prompt-crafter`** because `pcraft` and `prompt-craft` are both taken on
PyPI; the import package and the command stay `pcraft`. The npm package is a **launcher, not a
port** — reimplementing a threshold in a second language is how a threshold drifts, so it forwards
to the Python that holds the truth and inherits its exit code.

For development:

```bash
pip install -e ".[dev]"
```

The core is **GPU-free and runs anywhere** — the whole test suite executes against a mock
generator and verifier, which is what proves the plugin boundary actually holds. The `[image]`
extra (torch/diffusers) and `[synth]` extra (DSPy + a hosted LM) wire the real generator,
verifiers and synthesizer. **Neither is needed to run, test, or evaluate the core.**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft list              # contract ids in the store
pcraft validate          # resolve + compile the question DAG, no generate
pcraft gate <image>      # check an image against a contract
pcraft recipe            # Cloud Kontext + Fill graph (char:ashen-reaver-cloud); non-reference methods refuse
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## What a contract looks like

Not a prose prompt. A list of **atomic, depictable, individually checkable** claims:

- **`must_have`** — a garment, a palette, a silhouette, a sigil. Each carries a `check_type`
  (which gate tier verifies it), a `severity`, and optionally a `depends_on` edge so a claim is
  only meaningful when its parent passed. There is no point verifying the colour of an axe that
  is not there.
- **`must_not`** — anti-constraints, verified as **absence on the pixels**. Not a negative
  prompt: negative prompts leave residual features and fall to paraphrase.
- **`identity_ref`** — a reference plate. **Identity is conditioning, not tokens.** Anatomical
  text makes a diffusion model render a specimen; a reference image binds the specific face.

Contracts inherit — a character extends a faction — and inheritance is **fail-closed**: a child
may *raise* a requirement, never relax or silently drop one it inherited.

## The gate

Three tiers, cheapest deciding first, escalating only when a cheap answer is unclear. A
dependency-ordered pass means a failed parent marks its children N/A rather than scoring
nonsense.

**The verifier is always a different model family from the generator**, enforced by a guard that
refuses to run otherwise. A model is a poor judge of its own output, and that is the least
speculative part of this design.

**Exit codes distinguish four different things**, because a caller reading one number needs to
tell them apart:

| exit | meaning |
|---|---|
| `0` | the gate ran and every required atom passed |
| `1` | bad arguments or a malformed contract |
| `2` | it ran, and a required atom **failed** |
| `3` | it ran, and the result is **unconfirmed** — the human band |
| `4` | it **could not run** — no readable input, or no required tier available |

That last row is the one that matters. "I could not check" and "I checked and it is bad" are
different facts, and collapsing them is a documented source of real harm — it is why browsers
soft-fail certificate revocation, and why monitoring standards have carried a distinct *unknown*
verdict since the 1990s. Every gate transcript also reports **how many required tiers actually
executed**, independently of the verdict, so a gate that quietly stopped checking cannot read as
a pass.

**CLIPScore is not used as the gate metric.** It behaves as a bag of concepts — blind to which
attribute belongs to which object, to counts, and to relations. It is documented as known-broken
in the verifier interface so nobody reintroduces it.

## Honest status

**v1.0.0 — the INTERFACES are stable. The pictures are not finished, and this document does not pretend otherwise.**

A `1.0.0` here is a claim about the CLI, the import paths, the exit codes and the two on-disk
formats — enumerated in [STABILITY.md](STABILITY.md), along with what is deliberately excluded.
It is not a claim that the plate lands in the pixels. The gaps below are real and they get
better in minor releases; what stops moving is the surface you build against.

| | |
|---|---|
| Core | **516 tests passing** (counted 2026-08-31), GPU-free, deterministic. `verify` runs version coherence, lint, typecheck, the suite, the suite again under `-O`, and a package build — then **names what it did not check**. It lints and typechecks itself, pinned by a test so the targets cannot narrow back |
| Predicates | the eleven compound decision points in `core/` are **mutation-tested** — 20 of 21 mutants killed, and [the survivor is named](scripts/mutate_predicates.py) rather than hidden |
| SDXL conditioning | ControlNet OpenPose, IP-Adapter, LoRA, **InstantID**, and regional inpaint are **wired and covered by fake-torch tests**. InstantID and IP-Adapter cannot share one generate. Two IP-Adapter plates stay on one adapter (all images; scale is the strongest lock). Local `generate()` **ran** on the 5090 (2026-08-18, seed `169405236028824`, kind `controlnet_ip`). The frame is orcish; grip, sigil, and bracer did not land. |
| Flux encoder | Text-only and **Fill inpaint** are wired (fake-torch). ControlNet pose, IP-Adapter, LoRA, and InstantID stay refused (wrong family). `method=reference` writes the Cloud recipe graph and refuses to pretend Kontext ran locally (`GATE_CLOUD_SUBMIT`). |
| Cloud recipe | `pcraft recipe` emits Kontext stitch + in-graph left crop + fist-only Flux Fill. `method=reference` is that path. A live Cloud submit (job `06668d4c`, 2026-08-18) produced a single-panel crop and kept the bracer. |
| Gate | Tier-2 is a real DSG expansion (entity / attribute / relation). Escalation is a contrastive checkpoint. Receipts store the attempt story, not just a retry count. |
| Offline synth | `compile_synthesizer` pins against an **external** gate metric (`dspy.GEPA` when `[synth]` is installed). A live compile **ran** 2026-08-18 on local Ollama `hermes3:8b` (600B was not up). Pinned `sprite.synth.v1-gepa.json` (`generated_by=gepa`). The seed `sprite.synth.v1.json` is untouched. The per-asset loop still uses `TemplateSynthesizer`. The CLI still will not invent a pixel metric. |
| Identity sub-gate | scores CLIP-I and is **not wired** into `orchestrate`. Thresholds 0.55 / 0.05 have no holdout. Placeholders. |
| Real canon | the shipped example contract is a **generic invention**, not any real project's canon. Binding real canon is a deliberate, human decision |

Three claims that earlier versions of this document made and that measurement did not support,
corrected here rather than quietly dropped:

- The three-zone thresholds were described as *calibrated against a human-labelled holdout*. They
  are not. They are defaults.
- The rule that a generative model is never its own gate was stated as though a study had
  established it. The supporting evidence is **convergent rather than direct** — discriminative
  yes/no polling is measurably more stable than open-ended captioning, models cannot reliably
  self-correct without external feedback, and self-recognition tracks self-preference bias. No
  single study runs the head-to-head. The rule is sound; the certainty was overstated.
- Conditioning was described as unread, then as unimplemented. SDXL now **reads** the assembled
  refs in code. A live local `generate()` on this machine has now been run. Wired-and-applied
  is not the same as the plate landing in the pixels.
- `verify` was described by listing the legs it runs, which invited the reading that a green
  `verify.py` is a green CI. It is not — the dependency audit runs as a separate CI step. The
  gate now prints what it did **not** check, and `--audit` exists for when you want that leg
  locally. In the same pass: the gate had never linted or typechecked its own source, and the
  lint rule set was inherited from whatever tool version happened to resolve rather than
  declared. Both were fixed in v0.4.0. A check that reads as live while doing less than it
  appears to is the exact failure this project exists to catch, and it was in the tooling.

## Requirements

| | |
|---|---|
| Python | **3.11+** (CI runs 3.11 and 3.13 on the core + `[dev]`. The `[image]` extra is not claimed on 3.11.) |
| Platforms | pure Python, no compiled extensions in the core — developed on Windows 11, CI on `ubuntu-latest` |
| Dependencies | the core needs only `pydantic`. GPU work lives behind optional extras |

## Trust and threat model

- **Data touched** — contract JSON you point it at, the images you pass it, and provenance
  records written under the directory you name. Nothing else is read.
- **Data NOT touched** — no credentials of any kind are read, stored or transmitted. **No
  telemetry, analytics or usage counting**: there is no opt-out because there is nothing to opt
  out of. The core imports no networking library at all.
- **Network egress** — none from the core. The optional `[image]` and `[synth]` extras reach a
  model host by their nature; that is the only network path, and installing them is a choice.
- **Permissions** — ordinary user permissions. No elevation, no service installation, no registry
  or system-settings writes.
- **The sharp edge, disclosed rather than claimed away** — **file operations are not sandboxed.**
  `--records-dir` and `--db` write wherever you point them, deliberately, because this is a
  local-first tool. Point them somewhere you intend.
- **Errors** — deliberate refusals carry a code, a message and a hint, and **raise rather than
  `assert`**, so `-O` cannot delete them; the suite runs a second time under `-O` to prove it.
  Unexpected failures print a traceback only under `--debug`.

## Support status

`main` is the only supported state. No release channel, no backport policy, no SLA. This is
studio infrastructure published in the open, not a product with a support contract.

## How the pieces are arranged

`core/` is domain-agnostic and imports zero diffusion or torch symbols — a domain plugin exports
exactly three things: a generator, a list of verifiers, and an encoder ruleset. Adding a new
domain is a new sibling under `domains/`; nothing in `core/` changes. The GPU-free suite is what
keeps that claim honest.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | list | validate | demo | replay | doctor | schema | recipe | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

Encoder rules under `domains/image/rules/` are **generated** from a verified recipe database, not
hand-written, and carry a generation header. Every bound asset writes a **replayable provenance
receipt** pinning the contract hash, the synthesizer artifact, the generator and seed, the
verifier version, and the full per-atom gate transcript.

Design rationale, the standards this repo scores itself against, and the named undo for every
irreversible action live in [`STANDARDS.md`](STANDARDS.md) and
[`COMPENSATORS.md`](COMPENSATORS.md).

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md). Author: mcp-tool-shop. Dogfood
swarm on this tree: Grok (xAI).

## License

MIT — see [LICENSE](LICENSE). The licence of any *model* used through this tool is a separate
question and is not covered by it.
