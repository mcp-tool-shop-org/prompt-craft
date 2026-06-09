# COMPENSATORS — named undo for every irreversible action

> **Workflow standard #3 (NAMED_COMPENSATORS) — NO SKIP.** Every tool call that touches
> the world outside this working tree gets a named compensating action, the command to
> run it, the post-rollback state, and a named owner. Heritage: Sagas (Garcia-Molina &
> Salem, SIGMOD 1987). A call with no entry here may not be in the pipeline.

This file covers two scopes:
1. **Scaffold-time** actions already taken (or taken on each push) by the operator.
2. **Run-time** actions the pipeline takes per asset (these are registered in code at
   `core/loop/compensators.py` and the registry is the executable mirror of this table).

---

## 1. Scaffold-time irreversible actions

| # | Action | When | Compensator (command to undo) | Post-rollback state | Owner |
|---|--------|------|-------------------------------|---------------------|-------|
| S1 | `gh repo create mcp-tool-shop-org/prompt-craft --private` | **DONE 2026-06-09** (this session) | `gh repo delete mcp-tool-shop-org/prompt-craft --yes` then `rm -rf E:/AI/prompt-craft` | Org repo gone; local clone removed; no orphaned remote refs | Director (Mike) — repo creation is an owned action; agent executes only with the public/private decision made (chose **private**) |
| S2 | `git push origin main` (scaffold + subsequent commits) | each push | `git push origin --force-with-lease origin <prev-sha>:main` (rewind) or `git revert <sha> && git push` (forward undo, preferred) | Remote `main` at the prior good commit; history preserved if reverted | Director / scaffolder |
| S3 | `gh repo edit` (visibility / topics / description) | if run | `gh repo edit mcp-tool-shop-org/prompt-craft --visibility private` (restore) | Repo metadata restored to private + prior description | Director |

> S1's compensator is **destructive** (deletes the repo). It is listed for completeness;
> in practice S1 is undone only if the whole scaffold is abandoned. The default undo for a
> bad push is the **forward** compensator S2 (`git revert`), not the destructive S1.

---

## 2. Run-time irreversible actions (per-asset pipeline)

These are the actions the synth -> generate -> gate -> retry -> **bind** loop can take that
escape the working tree. Each is mirrored by a named function in
`src/pcraft/core/loop/compensators.py`. A bind happens **only after every required Assert
passes** (ANDON_AUTHORITY); the compensator exists for the case where a later step (or a
human) rejects an already-bound asset.

| # | Action | Compensator (named fn) | Post-rollback state | Owner |
|---|--------|------------------------|---------------------|-------|
| R1 | **bind-to-canon** — register an approved asset into the game's canon registry | `unbind_from_canon(asset_id)` — remove the registry entry + revert the canon-registry file to its pre-bind revision | Asset no longer canon; registry byte-identical to pre-bind; the rendered file remains in `records/` for audit | Pipeline (bind step) / Director approves the bind |
| R2 | **records/ write** — persist an asset receipt (provenance record) | `delete_record(record_id)` | Receipt removed; provenance index re-indexed without it | Pipeline (receipt step) |
| R3 | **human-escalation ticket** — open a checkpoint ticket when the gate is UNCERTAIN or retries are exhausted | `close_escalation(ticket_id, resolution)` | Ticket closed with a resolution note; no pending human action | Pipeline (uncertainty gate) / Director resolves |
| R4 | **encoder rules regeneration** — `scripts/sync_rules_from_readouts.py` overwrites `domains/image/rules/encoder_craft.md` from the readouts `prompt-craft` lane | `git checkout -- src/pcraft/domains/image/rules/encoder_craft.md` (it is generated + committed, so git is the undo) | The encoder rules return to the last committed generation; idempotent re-run reproduces the same file from the same DB revision | Sync script / scaffolder |

### Notes on the run-time compensators

- **Idempotency over rollback where possible (Parnas + Sagas).** The rules sync, the receipt
  write, and the question-DAG compile are designed to be *idempotent* — re-running with the
  same inputs reproduces the same output — so the cheapest "undo" is usually "re-run from the
  pinned inputs," not a destructive delete.
- **Bind is the only genuinely external, genuinely destructive run-time action.** It is gated
  twice: (a) every required Assert must pass before the loop reaches bind (andon), and (b) the
  Director approves the first canon bind for any new game/faction. Until then the example
  contract is **generic, non-canon** — binding it touches nothing real.
- The executable registry in `core/loop/compensators.py` is the source of truth; this table
  is the human-readable mirror. If they drift, the code wins and this file is stale — fix it.
