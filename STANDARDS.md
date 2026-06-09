# STANDARDS — the six workflow standards, scored 0–3

> Per the mcp-tool-shop **workflow standards** (June 2026 newsletter, Issue 5). Every workflow
> we ship scores itself against the six on a 0–3 scale with one paragraph of evidence per score.
> `prompt-craft` is itself a workflow (synth → generate → gate → retry → bind), so it scores
> itself here.
>
> **Scale:** `0 MISSING` · `1 PARTIAL` (in prose, not enforced) · `2 PRESENT` (a step enforces it) ·
> `3 EXEMPLARY` (enforced + documented + a test/receipt proves it).
>
> **Status: SCAFFOLD — proofs GREEN.** The scores below are backed by the GPU-free core test suite
> (`pytest` → **42 passed**). Each row names the concrete artifact and the test that proves it.
> Re-run `pytest` to re-verify; this file reflects actual results, not estimates.
> **Total: 17 / 18.** One standard sits at 2 with a named remediation.

| # | Standard | Score | Concrete artifact | Proof (green) |
|---|----------|-------|-------------------|---------------|
| 1 | **PIN_PER_STEP** | **3** | `core/receipt/asset_record.py` persists `{contract_hash, compiled_synth_id, generator_id+seed+sampler, conditioning, verifier_ids, thresholds_version, question_dag, gate_transcript, retry_count, decision}`; the synthesizer is a pinned `compiled/*.json` artifact | `test_receipt_replay.py` — a receipt round-trips and `replay` reconstructs the question DAG bit-for-bit; drift is detected. `test_end_to_end_demo.py` asserts the pinned fields |
| 2 | **ANDON_AUTHORITY** | **3** | `core/loop/orchestrate.py` binds **only** on `ADVANCE` (every required atom PASS); a failed required atom or a violated `must_not` halts into the repair ladder, then escalates | `test_orchestrate_andon.py` — a failed `face` atom and a present `no_human_face` both escalate, never bind |
| 3 | **NAMED_COMPENSATORS** | **3** | `COMPENSATORS.md` (no-skip) mirrored by `core/loop/compensators.py`; the loop calls `require(action)` before every irreversible step; the `gh repo create` is logged (S1) | `test_compensators.py` — an unregistered irreversible action is refused; every compensator names an owner + post-rollback state |
| 4 | **DECOMPOSE_BY_SECRETS** | **3** | `core/` (contract, loop, gate harness, synth, optimize, receipt) vs `domains/*` (generator, verifier, encoder rules). `core/` imports zero diffusion/torch symbols | `test_core_is_gpu_free.py` — importing all of `core/` pulls no torch/diffusers, and a static scan finds no such import; the whole loop runs on mocks |
| 5 | **UNCERTAINTY_GATED_HUMANS** | **2** | `core/gate/thresholds.py` is 3-zone per-clause; only `UNCERTAIN` (and an unconfirmable required atom) routes to escalation — never a silent pass. The escalation reason names the failed/unconfirmed atoms | `test_thresholds.py` + `test_gate_harness.py` — zones + the SKIPPED-required → UNCERTAIN roll-up are green. **Remediation:** the human-checkpoint message is not yet the full contrastive "you probably thought X; I chose Y" artifact with a test (owner: pipeline; next session) |
| 6 | **EXTERNAL_VERIFIER** | **3** | `core/gate/family_guard.py` hard-refuses `generator_family == verifier_family`; the gate sees only `{asset, clauses}`; CLIPScore is documented BANNED in `verifier_iface.py` | `test_family_guard.py` — same-family raises, SigLIP2 siblings normalize to one family, CLIPScore is refused as a gate metric |

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

**3 · NAMED_COMPENSATORS.** No skip taken or allowed. `orchestrate.run` calls `require("records-write")`
and `require("bind-to-canon")` before persisting + binding, and `require("escalation-ticket")` before
a human handoff — each must have a registered named undo with an owner or the loop refuses to act.
See `COMPENSATORS.md`.

**4 · DECOMPOSE_BY_SECRETS.** A plugin exports exactly three secrets — a `Generator`, tiered
`Verifier`s, and an `encoder-craft` ruleset. When the diffusion model changes, only the plugin
changes. The GPU-free mock test of the full loop is the executable proof the secret is actually
hidden.

**5 · UNCERTAINTY_GATED_HUMANS.** Humans are gated by the calibrated UNCERTAIN band, not by step
count. An unconfirmable required atom (SKIPPED/NA) rolls up to UNCERTAIN — never a silent pass. The
remaining gap is presentational: the escalation currently emits a reason string naming the failed
atoms; the full contrastive checkpoint message + its test is the named remediation.

**6 · EXTERNAL_VERIFIER.** Synthesizer = a 600B LLM; generator = diffusion; gate = a different VLM
family. `family_guard` refuses same-family generator/verifier (the whole `google/siglip2-*` line is
one family). The gate never sees the generator's reasoning. CLIPScore is rejected as the gate metric
and documented known-broken so nobody reintroduces it.

## Remediation

One item, one owner: **UNCERTAINTY_GATED_HUMANS → 3** by wiring the contrastive human-checkpoint
message ("the gate scored the crest 0.55 — it may read as bronze not gold; confirm or reject") as a
tested artifact (pipeline, next session). Everything else is at 3 with a green proof.
