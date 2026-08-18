# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

A version here marks **a state of the gate** — what it can check, what it refuses, and what it
has never been able to prove. The `[image]` path has not executed on any machine to date, so
every entry below concerns the GPU-free core.

## [Unreleased]

### Added

### Fixed

### Changed

## [0.2.0] — 2026-08-18

**The gate learned to say "I could not check."**

### Added

- **A four-way exit contract.** `0` every required atom passed · `1` bad arguments or contract ·
  `2` a required atom failed · `3` unconfirmed, the human band · `4` **could not run**. Merging
  "could not check" with "checked and it is bad" is a documented source of real harm — it is why
  browsers soft-fail certificate revocation, and why monitoring standards have carried a distinct
  *unknown* verdict since the 1990s.
- **`Zone.UNAVAILABLE`**, the roll-up twin of that split. Without it the transcript kept reporting
  UNCERTAIN when nothing had scored, so the merge the exit code dropped survived one layer down.
- **A tier census** on every transcript — how many required tiers *actually executed*, carried
  independently of the verdict. A gate that quietly stopped checking can no longer read as a pass.
- **`MustNot.severity`.** A negation's blocking power now matches the evidence behind the check
  enforcing it. Confirming a thing is *absent* is a different and less established capability than
  confirming it is present; a negation whose verifier is not calibrated for absence reports
  without blocking. The default stays `required`, so no existing contract changed meaning.
- **Fail-closed inheritance for negations.** A character contract may raise an inherited
  anti-constraint's severity, never relax it — the guard `must_have` always had, extended to
  `must_not` the moment a negation could carry a severity at all.
- **A mutation harness** over the eleven compound predicates in `core/`. First pass against the
  then-77-test suite: 8 mutants killed, **13 survived**. After fixtures: 20 killed, and the single
  survivor is reported rather than papered over.
- **Dependency scanning in CI** (`pip-audit`), and a `verify` script running the suite, the suite
  under `-O`, and a package build in one command.
- First callers for surfaces nothing had ever exercised: the identity sub-gate, `plugin.detect`'s
  unknown-domain path, `wrap_error`, `classify_failure`.

### Fixed

- **The gate scored images it never opened.** Given a path that did not exist it marked every atom
  SKIPPED — its verifiers reported themselves unavailable before anything touched the path —
  printed an overall verdict, and **exited 0**. A missing file, an unreadable file, and "extras
  not installed" were indistinguishable to any caller reading the exit code.
- **A substring back door routed garment claims to identity repair.** Any atom id *containing*
  `face`, `palette`, `sigil`, `identity` or `insignia` escalated to reference-plate conditioning,
  so a failed species or costume claim was treated as a likeness miss. Only ids that *are* the
  plate may request it now. Independently, the literature documents the same conflation: identity
  encoders mistake a palette change for identity drift.
- **A severity check that severity could not override.** Two sites read `severity is required
  **or** polarity is negate`; that `or` meant an `optional` negation blocked anyway. Harmless
  while negations were required by construction, silently wrong the moment they were not.
- **The wheel build failed** on a duplicate archive path. Four `force-include` entries re-added
  trees the package already shipped; the whole table is deleted rather than the one path that
  happened to error first.
- **Schema-invalid records dumped a raw traceback** with no `--debug`. They now carry a structured
  error.
- **`family_guard` approved everything when handed a string** where a list was expected — Python
  iterated it character by character, so `sdxl` against `sdxl`, the one case the guard exists to
  refuse, passed. It now refuses the wrong shape outright.
- **A one-character atom licensed almost any prompt.** The synthesizer's coverage check matched
  substrings in both directions, so an atom of `a` admitted arbitrary trailing prose. The
  permissive direction is floored at eight characters; the strict direction is unchanged.

### Changed

- **The README is a front door rather than a design document**, and two claims it made that
  measurement did not support are corrected in place rather than quietly dropped: the three-zone
  thresholds were never calibrated against a human-labelled holdout, and the rule that a
  generative model is never its own gate rests on convergent evidence, not a head-to-head study.

## [0.1.0] — 2026-06-09

Initial scaffold. The GPU-free `core/`, the `image/sprite` reference plugin, and an end-to-end
loop over a deliberately generic example contract.
