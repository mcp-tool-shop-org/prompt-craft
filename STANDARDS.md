# STANDARDS — the six workflow standards, scored 0–3

> Per the mcp-tool-shop **workflow standards** (June 2026 newsletter, Issue 5). Every workflow
> we ship scores itself against the six on a 0–3 scale with one paragraph of evidence per score.
> `prompt-craft` is itself a workflow (synth → generate → gate → retry → bind), so it scores
> itself here.
>
> **Scale:** `0 MISSING` · `1 PARTIAL` (in prose, not enforced) · `2 PRESENT` (a step enforces it) ·
> `3 EXEMPLARY` (enforced + documented + a test/receipt proves it).
>
> **Status: SCAFFOLD.** Scores below reflect the committed architecture. Each row names the
> concrete artifact and the **proof** (the test that verifies it). Rows whose proof test is not
> yet green are marked `(proof: pending)` and held at **2** until the named test passes — these
> graduate to 3 as the core mock-test suite (written in this same scaffold) goes green.
> **NAMED_COMPENSATORS is fully present from commit 1** (see `COMPENSATORS.md`).

| # | Standard | Score | Concrete artifact | Proof |
|---|----------|-------|-------------------|-------|
| 1 | **PIN_PER_STEP** | 2 → 3 | `core/receipt/asset_record.py` persists `{contract_hash, compiled_synth_id, generator_id+seed+sampler, conditioning_inputs, verifier_id+version, gate_transcript, thresholds_version, retry_count, decision}`; `core/optimize/artifact.py` pins the compiled synthesizer as a file (`domains/image/compiled/sprite.synth.v1.json`) | `tests/test_receipt_replay.py` — a receipt round-trips and `pcraft replay <record>` reconstructs the same question-DAG byte-for-byte *(proof: pending)* |
| 2 | **ANDON_AUTHORITY** | 2 | `core/loop/orchestrate.py` binds **only after every `required` Assert passes**; any failed `required` gate atom (or pre-gen Assert) halts the bind — bad output never propagates downstream | `tests/test_orchestrate_andon.py` — a contract whose required atom fails never reaches bind *(proof: pending)* |
| 3 | **NAMED_COMPENSATORS** | **3** | `COMPENSATORS.md` (scaffold + run-time tables, NO skip) mirrored by an executable registry in `core/loop/compensators.py`; the `gh repo create` of this very repo is logged (S1) | `tests/test_compensators_registry.py` — every registered irreversible action has a named, callable compensator with an owner *(proof: pending — table itself is complete now)* |
| 4 | **DECOMPOSE_BY_SECRETS** | 2 → 3 | The entire `core/` (stable: contract, loop, gate harness, synth signature, optimize, receipt) vs `domains/*` (volatile: generator, verifier, encoder rules) boundary **is** this standard — Parnas by secret, not by step. `core/` imports zero diffusion/torch symbols | `tests/test_core_is_gpu_free.py` — asserts no `torch`/`diffusers`/CUDA import is reachable from `core/`, and the full core suite runs with a **mock** Generator + Verifier *(proof: pending)* |
| 5 | **UNCERTAINTY_GATED_HUMANS** | 2 | `core/gate/thresholds.py` is 3-zone per-clause (`PASS`/`UNCERTAIN`/`FAIL`); only the `UNCERTAIN` band routes to a human checkpoint, framed **contrastively** ("the gate scored the crest 0.55 — it may read as bronze not gold; confirm or reject"). Retry-exhaustion escalates (R3 ticket) | `tests/test_thresholds_zones.py` + `tests/test_escalation_message.py` *(proof: pending)* |
| 6 | **EXTERNAL_VERIFIER** | 2 → 3 | `core/gate/family_guard.py` **hard-refuses** to run if `generator_family == verifier_family`; the gate receives only `{rendered asset, contract clauses}` — never the synthesizer's prompt text or coverage rationale. **CLIPScore is documented as BANNED** as the gate metric in `core/gate/verifier_iface.py` | `tests/test_family_guard.py` — raises when families match; `tests/test_gate_input_blind.py` — gate input excludes synth rationale *(proof: pending)* |

## Per-standard evidence

**1 · PIN_PER_STEP.** The asset record is *both* the provenance receipt and the training set for
the offline optimizer — the same pinned fields (model id, seed, sampler, compiled-program id,
verifier id+version, thresholds version, the per-atom gate transcript) that make a run replayable
are the features GEPA optimizes against. "If you cannot replay last week's run bit-for-bit, you
have a séance." The synthesizer is a **pinned compiled artifact** (`compiled/*.json`), never a
hand-edited mega-prompt; GEPA runs **offline** and freezes the artifact, the cheap local model
runs the frozen prompt per asset.

**2 · ANDON_AUTHORITY.** Two halt points: the **pre-generation Assert** (every required atom has a
non-empty coverage phrase, *before* any GPU spend) and the **gate** (every required atom clears its
PASS threshold on pixels). Either failing halts the loop into the retry/repair ladder; bind is
unreachable until all required Asserts are green. Bad output cannot flow into canon.

**3 · NAMED_COMPENSATORS.** No skip taken or allowed. The only genuinely external, genuinely
destructive run-time action is **bind-to-canon**, which has a named `unbind_from_canon` and is
gated by Director approval for any first canon bind. The scaffold-time `gh repo create` is logged
with its destructive compensator. See `COMPENSATORS.md`.

**4 · DECOMPOSE_BY_SECRETS.** A domain plugin exports exactly three secrets — a `Generator`, a list
of `Verifier`s, and an `encoder-craft` ruleset — plus optional subdomain refinements (sprite adds a
cross-view CLIP-I sub-gate). When the diffusion model changes, only the plugin changes; `core/`
(contract schema, loop, gate harness, optimizer, receipt) is untouched. The GPU-free mock test of
`core/` is the executable proof that the secret is actually hidden.

**5 · UNCERTAINTY_GATED_HUMANS.** Humans are gated by the calibrated UNCERTAIN band, not by step
count. Thresholds are per-clause and versioned against a human-labeled holdout, recalibrated when
the generator or verifier checkpoint changes (both pinned). The checkpoint prompt is contrastive by
construction.

**6 · EXTERNAL_VERIFIER.** Synthesizer = a 600B LLM; generator = diffusion; gate = a *different VLM
family*. `family_guard` refuses same-family generator/verifier. The gate never sees the generator's
reasoning. CLIPScore is rejected as the gate metric (bag-of-concepts, blind to attribute binding /
counts / relations) and documented as known-broken so nobody reintroduces it.

## Remediation

No standard scores below 2 by design. The five rows at "2 → 3" graduate to 3 when their named proof
test is green — those tests are part of this scaffold's GPU-free core suite. This file is updated
with the actual `pytest` result, not an estimate, once the suite runs.
