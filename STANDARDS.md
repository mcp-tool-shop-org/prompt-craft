# STANDARDS — the six workflow standards, scored 0–3

> Per the mcp-tool-shop **workflow standards** (June 2026 newsletter, Issue 5). Every workflow
> we ship scores itself against the six on a 0–3 scale with one paragraph of evidence per score.
> `prompt-craft` is itself a workflow (synth → generate → gate → retry → bind), so it scores
> itself here.
>
> **Scale:** `0 MISSING` · `1 PARTIAL` (in prose, not enforced) · `2 PRESENT` (a step enforces it) ·
> `3 EXEMPLARY` (enforced + documented + a test/receipt proves it).
>
> **Status: SCORED AGAINST THE SUITE, 2026-08-18.** The GPU-free suite collects **105**. Each row
> names the artifact and what the tests actually prove — not what the comments promise.
> Wave-1 of the prompt-craft dogfood swarm (`swarm-1787033129-beab`) measured two of the
> previous `3`s as unearned: the mechanism exists, the public door or one persist path does
> not go through it, and the suite encodes that gap as passing. Those rows drop to `2`.
> **Total: 15 / 18.** Three standards sit at 2 with named remediations.

| # | Standard | Score | Concrete artifact | Proof (green) |
|---|----------|-------|-------------------|---------------|
| 1 | **PIN_PER_STEP** | **3** | `core/receipt/asset_record.py` persists `{contract_hash, compiled_synth_id, generator_id+seed+sampler, conditioning, verifier_ids, thresholds_version, question_dag, gate_transcript, retry_count, decision}`; the synthesizer is a pinned `compiled/*.json` artifact | `test_receipt_replay.py` — a receipt round-trips and `replay` reconstructs the question DAG bit-for-bit; drift is detected. `test_end_to_end_demo.py` asserts the pinned fields |
| 2 | **ANDON_AUTHORITY** | **3** | `core/loop/orchestrate.py` binds **only** on `ADVANCE` (every required atom PASS); a failed required atom or a violated `must_not` halts into the repair ladder, then escalates | `test_orchestrate_andon.py` — a failed `face` atom and a present `no_human_face` both escalate, never bind |
| 3 | **NAMED_COMPENSATORS** | **2** | `COMPENSATORS.md` (no-skip) mirrored by `core/loop/compensators.py`; `require(action)` runs before the ADVANCE persist | `test_compensators.py` proves the registry refuses an unregistered name and that every registered compensator has an owner + post-state. It does **not** prove every persist is guarded: the escalation branch of `orchestrate.run` calls `persist()` with no `require("records-write")`. A `3` needs a test that both persist paths refuse when that compensator is missing |
| 4 | **DECOMPOSE_BY_SECRETS** | **3** | `core/` (contract, loop, gate harness, synth, optimize, receipt) vs `domains/*` (generator, verifier, encoder rules). `core/` imports zero diffusion/torch symbols | `test_core_is_gpu_free.py` — importing all of `core/` pulls no torch/diffusers, and a static scan finds no such import; the whole loop runs on mocks |
| 5 | **UNCERTAINTY_GATED_HUMANS** | **2** | `core/gate/thresholds.py` is 3-zone per-clause; only `UNCERTAIN` (and an unconfirmable required atom) routes to escalation — never a silent pass. The escalation reason names the failed/unconfirmed atoms | `test_thresholds.py` + `test_gate_harness.py` — zones + the SKIPPED-required → UNCERTAIN roll-up are green. **Remediation:** the human-checkpoint message is not yet the full contrastive "you probably thought X; I chose Y" artifact with a test (owner: pipeline) |
| 6 | **EXTERNAL_VERIFIER** | **2** | `core/gate/family_guard.py` hard-refuses `generator_family == verifier_family`; CLIPScore is documented BANNED in `verifier_iface.py` | `test_family_guard.py` proves the function: same-family raises, SigLIP2 siblings normalize to one family, CLIPScore is refused. The only call site is `orchestrate.py`. `harness.evaluate` and `pcraft gate` invoke neither guard. A `3` needs a test that the public gate door refuses. Exploitable by a plugin author, not an end user |

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

**3 · NAMED_COMPENSATORS.** The registry and the ADVANCE path are real. `orchestrate.run` calls
`require("records-write")` and `require("bind-to-canon")` before the bound persist, and
`require("escalation-ticket")` before a human handoff. The escalation persist at the same
`persist()` helper is unguarded — a receipt can be written without `records-write` registered.
`test_compensators.py` proves the registry, not both doors. That is a `2`. See `COMPENSATORS.md`.

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
one family) **when `orchestrate.run` is the caller**. `pcraft gate` calls `harness.evaluate`
directly and never reaches the guard. CLIPScore is rejected as the gate metric and documented
known-broken so nobody reintroduces it — again, only on the orchestrate path. That is a `2`.

## Remediation

Three items, one owner each:

1. **NAMED_COMPENSATORS → 3** — `require("records-write")` on every `persist()`, including
   escalation; a test that both persist paths refuse when that compensator is missing (pipeline).
2. **EXTERNAL_VERIFIER → 3** — `harness.evaluate` calls `forbid_clipscore`; it takes a
   `generator_family` and calls `assert_distinct_families`; `pcraft gate` passes the plugin
   generator's family (or `--generator-family`); a test that the gate door refuses (pipeline).
3. **UNCERTAINTY_GATED_HUMANS → 3** — wire the contrastive human-checkpoint message ("the gate
   scored the crest 0.55 — it may read as bronze not gold; confirm or reject") as a tested
   artifact (pipeline).

A score returns to `3` only when the suite proves the missing door, not when the comment is
updated. Do not restore a `3` from a docs edit.
