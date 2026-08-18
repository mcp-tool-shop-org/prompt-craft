# Ship Gate

> No repo is "done" until every applicable line is checked.
> Copy this into your repo root. Check items off per-release.

**Tags:** `[all]` every repo · `[npm]` `[pypi]` `[vsix]` `[desktop]` `[container]` published artifacts · `[mcp]` MCP servers · `[cli]` CLI tools

---

## A. Security Baseline

- [x] `[all]` SECURITY.md exists (report email, supported versions, response timeline) (2026-08-17)
- [ ] `[all]` README includes threat model paragraph (data touched, data NOT touched, permissions required)
- [x] `[all]` No secrets, tokens, or credentials in source or diagnostics output (2026-08-17)
- [x] `[all]` No telemetry by default — state it explicitly even if obvious (2026-08-17)

### Default safety posture

- [ ] `[cli|mcp|desktop]` SKIP: no kill/delete/restart-class action is implemented anywhere in this CLI scaffold (the only non-mock GPU/canon-bind path is unconditionally stubbed to raise `DEP_IMAGE_MISSING`)
- [ ] `[cli|mcp|desktop]` File operations constrained to known directories
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[mcp]` SKIP: not an MCP server

## B. Error Handling

- [x] `[all]` Errors follow the Structured Error Shape: `code`, `message`, `hint`, `cause?`, `retryable?` (2026-08-17)
- [x] `[cli]` Exit codes: 0 ok · 1 user error · 2 runtime error · 3 partial success (2026-08-17)
- [ ] `[cli]` No raw stack traces without `--debug`
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[desktop]` SKIP: not a desktop app
- [ ] `[vscode]` SKIP: not a VS Code extension

## C. Operator Docs

- [ ] `[all]` README is current: what it does, install, usage, supported platforms + runtime versions
- [ ] `[all]` CHANGELOG.md (Keep a Changelog format)
- [ ] `[all]` LICENSE file present and repo states support status
- [x] `[cli]` `--help` output accurate for all commands and flags (2026-08-17)
- [ ] `[cli|mcp|desktop]` Logging levels defined: silent / normal / verbose / debug — secrets redacted at all levels
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[complex]` SKIP: no background daemon, state file, or operational modes — a synchronous CLI

## D. Shipping Hygiene

- [ ] `[all]` `verify` script exists (test + build + smoke in one command)
- [ ] `[all]` SKIP: no git tag exists yet (pre-first-release scaffold) — nothing to compare the manifest's 0.1.0 against
- [ ] `[all]` Dependency scanning runs in CI (ecosystem-appropriate)
- [ ] `[all]` Automated dependency update mechanism exists
- [ ] `[npm]` SKIP: not an npm package
- [x] `[npm]` `engines.node` set · `[pypi]` `python_requires` set (2026-08-17)
- [ ] `[npm]` Lockfile committed · `[pypi]` Clean wheel + sdist build
- [ ] `[vsix]` SKIP: not a VS Code extension
- [ ] `[desktop]` SKIP: not a desktop app

## E. Identity (soft gate — does not block ship)

- [ ] `[all]` Logo in README header
- [ ] `[all]` Translations (polyglot-mcp, 8 languages)
- [ ] `[org]` Landing page (@mcptoolshop/site-theme)
- [ ] `[all]` GitHub repo metadata: description, homepage, topics

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
