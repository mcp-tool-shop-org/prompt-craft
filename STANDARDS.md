# STANDARDS — the six workflow standards, scored 0–3

> Per the mcp-tool-shop **workflow standards** (June 2026 newsletter, Issue 5). Every workflow
> we ship scores itself against the six on a 0–3 scale with one paragraph of evidence per score.
> `prompt-craft` is itself a workflow (synth → generate → gate → retry → bind), so it scores
> itself here.
>
> **Scale:** `0 MISSING` · `1 PARTIAL` (in prose, not enforced) · `2 PRESENT` (a step enforces it) ·
> `3 EXEMPLARY` (enforced + documented + a test/receipt proves it).
>
> **Status: SCORED AGAINST THE SUITE, 2026-08-18 (contrastive checkpoint).** A `3`
> is restored only from a named test, not from a comment edit.
> **Total: 18 / 18.**

| # | Standard | Score | Concrete artifact | Proof (green) |
|---|----------|-------|-------------------|---------------|
| 1 | **PIN_PER_STEP** | **3** | `core/receipt/asset_record.py` persists `{contract_hash, compiled_synth_id, generator_id+seed+sampler, conditioning, verifier_ids, thresholds_version, question_dag, gate_transcript, retry_count, decision}`; the synthesizer is a pinned `compiled/*.json` artifact | `test_receipt_replay.py` — a receipt round-trips and `replay` reconstructs the question DAG bit-for-bit; drift is detected. `test_end_to_end_demo.py` asserts the pinned fields |
| 2 | **ANDON_AUTHORITY** | **3** | `core/loop/orchestrate.py` binds **only** on `ADVANCE` (every required atom PASS); a failed required atom or a violated `must_not` halts into the repair ladder, then escalates | `test_orchestrate_andon.py` — a failed `face` atom and a present `no_human_face` both escalate, never bind |
| 3 | **NAMED_COMPENSATORS** | **3** | `COMPENSATORS.md` (no-skip) mirrored by `core/loop/compensators.py`; `require("records-write")` runs before every `persist()`, bound and escalated | `test_amend_loop.py` — both persist doors refuse with `STATE_NO_COMPENSATOR` when `records-write` is missing. `test_compensators.py` still proves the registry itself |
| 4 | **DECOMPOSE_BY_SECRETS** | **3** | `core/` (contract, loop, gate harness, synth, optimize, receipt) vs `domains/*` (generator, verifier, encoder rules). `core/` imports zero diffusion/torch symbols | `test_core_is_gpu_free.py` — importing all of `core/` pulls no torch/diffusers, and a static scan finds no such import; the whole loop runs on mocks |
| 5 | **UNCERTAINTY_GATED_HUMANS** | **3** | `core/gate/checkpoint.py` emits a contrastive "you probably thought X; I chose Y" artifact on every escalation; UNCERTAIN still never silent-passes | `test_feat_checkpoint.py` — an UNCERTAIN `face` at 0.55 produces the checkpoint; the loop reason *is* that text; a bound run has none |
| 6 | **EXTERNAL_VERIFIER** | **3** | `harness.evaluate` takes `generator_family`, calls `assert_distinct_families` and `forbid_clipscore`; `pcraft gate` passes the plugin generator family or `--generator-family` | `test_amend_gate.py` — `evaluate` refuses same-family and CLIPScore. `test_amend_cli.py` — `pcraft gate --generator-family siglip2` exits 2 with `GATE_SAME_FAMILY`. `test_family_guard.py` still proves the function |

## Per-standard evidence

**1 · PIN_PER_STEP.** The asset record is both the provenance receipt and the offline optimizer's
training set — the same pinned fields that make a run replayable are the features GEPA learns from.
`pcraft replay <record>` recomputes the contract hash and rebuilds the question DAG, asserting both
match (drift raises `STATE_REPLAY_DRIFT`). The synthesizer is a pinned compiled artifact, never a
hand-edited mega-prompt.

**2 · ANDON_AUTHORITY.** Two halt points: the pre-generation Assert (every required atom covered,
before any GPU spend) and the gate (every required atom PASS on pixels). The demo shows it live: the
faceless-hero failure (`face` scored below threshold) never binds — it runs the repair ladder
(`strengthen_identity`, because `face` is an identity atom) and escalates after the budget. The old
weapon-only gate shipped that character clean; this one cannot.

**3 · NAMED_COMPENSATORS.** No skip taken or allowed on either persist door. `orchestrate.run`
calls `require("records-write")` and `require("bind-to-canon")` before the bound persist, and
`require("records-write")` plus `require("escalation-ticket")` before the post-gate escalated
persist. The two early escalation returns that never build a record correctly require only the
ticket. See `COMPENSATORS.md`.

**4 · DECOMPOSE_BY_SECRETS.** A plugin exports exactly three secrets — a `Generator`, tiered
`Verifier`s, and an `encoder-craft` ruleset. When the diffusion model changes, only the plugin
changes. The GPU-free mock test of the full loop is the executable proof the secret is actually
hidden.

**5 · UNCERTAINTY_GATED_HUMANS.** Humans are gated by the calibrated UNCERTAIN band, not by a
silent pass. An unconfirmable required atom rolls up to UNCERTAIN. The escalation reason is the
contrastive checkpoint: what a silent-pass reader would have concluded, and what the gate chose,
per flagged atom. `test_feat_checkpoint.py` is the public door.

**6 · EXTERNAL_VERIFIER.** Synthesizer = a 600B LLM; generator = diffusion; gate = a different VLM
family. `evaluate` refuses same-family generator/verifier (the whole `google/siglip2-*` line is
one family) on every caller, including `pcraft gate`. CLIPScore is rejected as the gate metric
and documented known-broken so nobody reintroduces it.

## Remediation

None. All six standards are at 3 with a named green proof.
