# prompt-craft

> **Contract-driven generative-asset production.** A typed, depictable **contract** →
> a constrained **synthesizer** (every token traces to a depictable atom) → **generate** →
> a **different-family gate** (verifies the contract on the pixels) → **retry/repair** →
> **bind**. Domain-agnostic core + per-domain plugins (image · video · workflow).

**Status: SCAFFOLD (v0.1.0).** The GPU-free `core/` and the `image/sprite` reference plugin
are wired and mock-tested; the loop runs end-to-end on a **generic, non-canon** example contract.
Binding to any real game canon is **gated on the Director** (see *Gates* below). Private repo
under `mcp-tool-shop-org` — it references internal pipeline infra.

---

## Why this exists (the motivating failure)

A hero character was generated as a washed-out, faceless, generic nobody, and the operator
burned a loop tweaking tonemaps and re-rolling. **Root cause:** an opaque prose prompt fed the
text encoder a narrative it cannot ground, checked by *one* coarse advisory weapon-presence
test. The character lost its face, palette, and faction identity — and shipped clean, because
nothing verified those things.

The repo it supersedes (`trellis-sprite-pipeline`) modelled a character as:

```json
{ "name": "orc_berserker", "prompt": "hulking muscular orc … war axe … green skin, tusks …", "weapon_class": "axe" }
```

`weapon_class` was the **only** machine-checkable attribute, the gate was advisory, and it was
skipped entirely for the 4 of 6 sample characters with no weapon. prompt-craft replaces this
with a typed contract where face, palette, sigil, and silhouette are first-class, verified,
and blocking.

## The one idea, applied six ways

The asset pipeline is a **compiled program** (DSPy, arXiv:2310.03714): a declarative **contract**
is separated from the imperative **synthesize** module, separated from the offline **optimizer**.
The contract's atom list is **the same list used twice** — once to synthesize the prompt, once to
gate the pixels (DSG arXiv:2310.18235; TIFA arXiv:2303.11897). That single fact is what closes the
loop the opaque prompt left open.

```
        ┌─────────────┐   atoms    ┌──────────────┐  prompt   ┌───────────┐
        │  CONTRACT    │──────────▶│  SYNTHESIZE   │─────────▶│ GENERATE  │
        │ (typed       │            │ (600B, every  │           │ (diffusion│
        │  depictable  │            │  token traces │           │  + Control│
        │  atoms)      │            │  to an atom)  │           │  Net/IPA) │
        └─────┬────────┘            └──────────────┘           └─────┬─────┘
              │ same atoms                                            │ pixels
              ▼                                                       ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  GATE  — a DIFFERENT VLM family verifies the contract on the   │
        │  pixels. 3 tiers, cheapest decides first. CLIPScore is BANNED. │
        └─────┬──────────────────────────────────────────────────┬─────┘
              │ PASS                                              │ FAIL / UNCERTAIN
              ▼                                                    ▼
          BIND to canon                                  RETRY / REPAIR ladder
       (only after every required                    (verifier is the selector;
        Assert passes — andon)                         uncertainty → human gate)
```

## Architecture — the CORE / PLUGIN boundary

The split is **by Parnas secret** (DECOMPOSE_BY_SECRETS): *what stays the same across
image/video/workflow lives in `core/`; what changes per generator/verifier lives in a plugin.*
`core/` imports **zero** diffusion/torch symbols, so the whole core test suite runs with a **mock**
Generator + Verifier on any machine — that GPU-free test **is the proof the boundary holds**.

```
src/pcraft/
  core/                      DOMAIN-AGNOSTIC, GPU-free, mock-testable
    contract/                pydantic Contract; fail-closed faction→character loader;
                             atoms → DSG question-DAG; canonical provenance hash
    loop/                    synth→generate→verify→retry→bind state machine
                             (BLOCK/AMEND/VERIFY/ADVANCE verdicts); retry/repair ladder;
                             NAMED_COMPENSATORS registry
    gate/                    dependency-ordered harness; Verifier protocol (CLIPScore BANNED);
                             family_guard (hard-refuse same-family); 3-zone thresholds
    synth/                   DSPy Signature; visual_inventory anti-prose-dump guard;
                             pre-gen coverage Assert
    optimize/                OFFLINE GEPA compile; PINNED compiled artifact
    receipt/                 per-asset provenance record (replayable)
  cli/                       pcraft: synth | gate | bind | compile | replay | sync-rules
  domains/                   ── PLUGIN BOUNDARY ──
    image/                   a plugin exports Generator, Verifier[], encoder-craft rules
      generator/             SDXL (+ControlNet/IP-Adapter), Flux
      verifier/              siglip2 screen (Tier-0) · vqascore (Tier-1) · dsg (Tier-2)
      rules/encoder_craft.md GENERATED from the readouts prompt-craft lane (never hand-edited)
      compiled/              PINNED compiled synthesizer artifact
      subdomains/sprite/     8-dir CLIP-I consistency sub-gate; pose ControlNet; foot-anchor;
                             a GENERIC example faction→character contract; calibration
scripts/sync_rules_from_readouts.py   reads recipes.db (prompt-craft lane) → writes encoder_craft.md
```

A domain plugin exports exactly three secrets — a `Generator`, a list of `Verifier`s, and an
`encoder-craft` ruleset — plus optional subdomain refinements. Adding **video** or **workflow**
is a new sibling under `domains/`; **nothing in `core/` changes**.

## The gate — 3 tiers, cheapest decides first

| Tier | Verifier | Decides | Family |
|------|----------|---------|--------|
| 0 | **SigLIP2** zero-shot (sigmoid, per-query) | closed-set / presence atoms (palette, garment, silhouette) | `google/siglip2-*` |
| 1 | **VQAScore** (CLIP-FlanT5 `P('Yes')`) | compositional atoms + whole-contract screen | `clip-flant5` |
| 2 | **DSG** DAG (per-atom, dependency-ordered) | *localizes which atom failed* on a tier-1 fail/borderline | (QG LM, distinct) |

- **`family_guard` hard-refuses** to run if `generator_family == verifier_family`
  (EXTERNAL_VERIFIER). The gate sees only `{rendered asset, contract clauses}` — never the
  synthesizer's prompt or rationale. Doctrine, earned on this rig: a **generative VLM is never its
  own gate** (LLaVA-13B hallucinated greatswords on unarmed cooks at 0.90 confidence, P=0.26;
  discriminative SigLIP2 scored P=0.909).
- **CLIPScore is BANNED** as the gate metric — bag-of-concepts, blind to attribute binding /
  counts / relations. Documented as known-broken in `core/gate/verifier_iface.py`.
- **Dependency-ordered:** a NO parent forces N/A on its descendants (no "verify the colour of an
  axe that isn't there").
- **3-zone thresholds** per clause (`PASS` / `UNCERTAIN` / `FAIL`), calibrated against a
  human-labelled holdout; only the `UNCERTAIN` band routes to a contrastively-framed human
  checkpoint (UNCERTAINTY_GATED_HUMANS).
- **Sprite sub-gate:** after per-view gating, **CLIP-I** cross-view consistency (floor + low
  variance) catches silhouette/palette drift across the 8-direction turnaround (AnyCrowd
  arXiv:2603.15415).

## The synthesizer — constrained, compiled, anti-prose-dump

- A **`visual_inventory` scratchpad runs first**: each atom → `{depictable?, front_load_rank,
  token}`, pruning the un-depictable (backstory, intent). **Every token in the final prompt must
  trace to a row marked `depictable=true`** — the single strongest guard against the 600B's
  prose-dumping (RePrompt arXiv:2505.17540).
- **Two-stage emit:** Stage 1 free-form prose under the encoder rules (no grammar on the prose —
  token selection is a reasoning task, JSON-mode degrades it, "Let Me Speak Freely?"
  arXiv:2408.02442); Stage 2 a separate constrained pass wraps only the JSON envelope.
- **Pre-generation Assert** before any GPU spend: every `required` atom must have a non-empty
  coverage phrase, else backtrack (DSPy Assertions arXiv:2312.13382).
- **Identity is conditioning, not tokens** — LoRA / IP-Adapter on a reference plate binds the
  exact face/insignia that text cannot specify (IP-Adapter arXiv:2308.06721). The gate then
  verifies it rendered.
- **Compiled offline, run cheap:** GEPA (arXiv:2507.19457; >10% over MIPROv2, +6% avg up to +20%
  over GRPO) evolves the prompt against the gate's per-atom failure text **offline**; the frozen,
  **pinned** artifact runs on a cheap local model per asset. *Scale at optimize-time, small at
  run-time.*

## Standards & provenance

prompt-craft scores itself against the six mcp-tool-shop **workflow standards** — see
[`STANDARDS.md`](STANDARDS.md). Every irreversible action has a named undo with an owner — see
[`COMPENSATORS.md`](COMPENSATORS.md) (no-skip; the `gh repo create` of this repo is logged). Every
bound asset writes a replayable provenance receipt pinning the contract hash, the compiled
synthesizer id, the generator id+seed+sampler, the verifier id+version, and the full per-atom gate
transcript (PIN_PER_STEP).

## Encoder rules are generated, not authored

`domains/image/rules/encoder_craft.md` is **generated** by `scripts/sync_rules_from_readouts.py`
from the `prompt-craft` lane of the readouts sprites-knowledge DB (103 verified, source-cited
recipes; debunked folklore rendered as explicit DON'T rules). It is never hand-edited — the DB is
the single source of truth, and the file carries a generation header for replayability.

## Quickstart (GPU-free core)

```bash
python -m venv .venv && . .venv/Scripts/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                       # the GPU-free core suite — the proof the plugin boundary holds
pcraft gate --help
pcraft replay --help
```

The `[image]` extra (torch/diffusers) and `[synth]` extra (DSPy + an Ollama-Cloud LM) wire the
real generator, verifiers, and 600B synthesizer. They are **not** needed to run or test the core.

## Gates (human-in-the-loop)

- **Repo-first** is satisfied (private org repo, `main`, scaffold pushed).
- The **Director** gates: the first **real canon contract** (which game/faction — *not decided*;
  the scaffold ships only a generic `ashen_pact` example), any **canon binding**, and pushes of
  substantive content beyond the scaffold.
- **Watchdog up** before any GPU run; **look at every generated output**.

## Citations (corrected)

Self-critique limits = Valmeekam **arXiv:2310.08118** (not 2402.01817); CLIP-I-over-views =
AnyCrowd **arXiv:2603.15415** (drop 2411.13536); GEPA = ">10% / +6% avg, up to +20%"; DOMINO =
**arXiv:2403.06988**.

## License

MIT — see [LICENSE](LICENSE).
