# Ship Gate

> No repo is "done" until every applicable line is checked.
> Copy this into your repo root. Check items off per-release.

**Tags:** `[all]` every repo · `[npm]` `[pypi]` `[vsix]` `[desktop]` `[container]` published artifacts · `[mcp]` MCP servers · `[cli]` CLI tools

---

## A. Security Baseline

- [x] `[all]` SECURITY.md exists (report email, supported versions, response timeline) (2026-08-17)
- [x] `[all]` README includes threat model paragraph (data touched, data NOT touched, permissions required) (2026-08-18 — README "Trust and threat model": contract JSON / images / records touched; no credentials, no telemetry, no networking library in core; ordinary user permissions; the unsandboxed `--records-dir` disclosed as a deliberate local-first trade-off)
- [x] `[all]` No secrets, tokens, or credentials in source or diagnostics output (2026-08-17)
- [x] `[all]` No telemetry by default — state it explicitly even if obvious (2026-08-17)

### Default safety posture

- [ ] `[cli|mcp|desktop]` SKIP: no kill/delete/restart-class action is implemented anywhere in this CLI scaffold (the only non-mock GPU/canon-bind path is unconditionally stubbed to raise `DEP_IMAGE_MISSING`)
- [ ] `[cli|mcp|desktop]` SKIP: deliberately unconstrained and disclosed rather than claimed away (2026-08-18). `--records-dir`/`--db` write where the operator points them; confining a local-first CLI to a blessed directory makes it worse at its purpose. Stated as a sharp edge in the README threat model and the handbook security page, so it is a decision rather than a surprise
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[mcp]` SKIP: not an MCP server

## B. Error Handling

- [x] `[all]` Errors follow the Structured Error Shape: `code`, `message`, `hint`, `cause?`, `retryable?` (2026-08-17)
- [x] `[cli]` Exit codes: 0 ok · 1 user error · 2 runtime error · 3 partial success (2026-08-17)
- [x] `[cli]` No raw stack traces without `--debug` (2026-08-18 — reproduced: `pcraft replay` on a JSON-valid, schema-invalid record gives `error[IO_RECORD_INVALID]` with a hint and exit 2, no traceback; the raw pydantic dump it used to produce is fixed and the cause still rides `--debug`)
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[desktop]` SKIP: not a desktop app
- [ ] `[vscode]` SKIP: not a VS Code extension

## C. Operator Docs

- [x] `[all]` README is current: what it does, install, usage, supported platforms + runtime versions (2026-08-18 — rewritten as a front door; Requirements table states Python 3.11+, CI on 3.13, pure-Python core, Windows-developed / ubuntu CI; seven translations regenerated with the cache bypassed and all eight files verified carrying v0.2.0 and the full exit-code table)
- [x] `[all]` CHANGELOG.md (Keep a Changelog format) (2026-08-18 — real `[0.2.0]` and `[0.1.0]` entries with Added/Fixed/Changed, replacing the commented-out stub)
- [x] `[all]` LICENSE file present and repo states support status (2026-08-18 — MIT LICENSE present; "Support status" section in both README and handbook: `main` is the only supported state, no release channel, no backport policy, no SLA)
- [x] `[cli]` `--help` output accurate for all commands and flags (2026-08-17)
- [ ] `[cli|mcp|desktop]` SKIP: a synchronous single-shot CLI whose entire output IS its result (2026-08-18). It carries a binary `--debug` that controls traceback exposure; four graduated levels would be scaffolding for a daemon this is not. Redaction is moot — no credential is ever read, so none can be logged. Re-opens if a long-running or server mode is ever added
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[complex]` SKIP: no background daemon, state file, or operational modes — a synchronous CLI

## D. Shipping Hygiene

- [x] `[all]` `verify` script exists (test + build + smoke in one command) (2026-08-18 — `python verify.py --installed`: suite, suite again under `-O` to prove refusals raise rather than assert, then a package build; VERIFY OK)
- [x] `[all]` Version matches the git tag (2026-08-18 — pyproject `0.4.0` == tag `v0.4.0` == `npm/package.json` `0.4.0` == `_FALLBACK_VERSION`. Enforced mechanically, not by eye: `release.yml` fails the release if `$TAG != $PKG` or `$PKG != $NPM`, and `verify.py --installed` refuses when installed metadata disagrees with pyproject. **This item was skipped as "no git tag exists yet ... nothing to compare the manifest's 0.1.0 against" through four releases** — v0.2.0, v0.2.1, v0.3.0, v0.4.0 — and it is the exact check that would have caught the stale editable dist-info that broke a release twice)
- [x] `[all]` Dependency scanning runs in CI (ecosystem-appropriate) (2026-08-18 — `pip-audit --strict` in ci.yml, running after verify so a red audit is never read against an already-broken tree; locally: "No known vulnerabilities found")
- [ ] `[all]` SKIP: the org's GitHub Actions rule forbids adding `dependabot.yml` unless explicitly requested (2026-08-18). A standing tension between that rule and this gate, resolved in favour of the org rule and recorded rather than silently checked. `pip-audit` in CI covers the detection half; the update half is manual by policy
- [ ] `[npm]` SKIP: not an npm package
- [x] `[npm]` `engines.node` set · `[pypi]` `python_requires` set (2026-08-17)
- [x] `[pypi]` Clean wheel + sdist build (2026-08-18 — both build; the duplicate-archive-path collision from four redundant `force-include` entries is fixed at the cause, and `test_wheel_does_not_force_include_trees_already_in_packages` keeps it fixed)
- [ ] `[vsix]` SKIP: not a VS Code extension
- [ ] `[desktop]` SKIP: not a desktop app

## E. Identity (soft gate — does not block ship)

- [x] `[all]` Logo in README header (2026-08-18 — the Director's chosen mark, cropped to its lockup at 1322x408, at `docs/assets/logo.png`)
- [x] `[all]` Translations (polyglot-mcp, 8 languages) (2026-08-18 — ja/zh/es/fr/hi/it/pt-BR generated with `--no-cache`, and all eight files verified carrying v0.2.0, the 105 count and the full five-row exit table. The cache is bypassed deliberately: on a sibling repo it reported ok for seven languages while four carried a count from two releases earlier)
- [x] `[org]` Landing page (@mcptoolshop/site-theme) (2026-08-18 — landing page plus a six-page Starlight handbook; `npm run build` produces 7 pages, both index files and the pagefind search index)
- [x] `[all]` GitHub repo metadata: description, homepage, topics (2026-08-18 — description set, homepage points at the Pages site, 8 topics; verified by reading them back from the API)

---

## Gate Rules

**Hard gate (A–D):** Must pass before any version is tagged or published.
If a section doesn't apply, mark `SKIP:` with justification — don't leave it unchecked.

**Soft gate (E):** Should be done. Product ships without it, but isn't "whole."

**Checking off:**
```
- [x] `[all]` SECURITY.md exists (2026-02-27)
```

**Skipping:**
```
- [ ] `[pypi]` SKIP: not a Python project
```
