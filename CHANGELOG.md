# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

A version here marks **a state of the gate** — what it can check, what it refuses, and what it
has never been able to prove. The `[image]` path has not executed on any machine to date, so
every entry below concerns the GPU-free core.

## [Unreleased]

### Fixed

- **A one-character typo emptied a contract.** `Contract` was the only model set to
  `extra="ignore"`; `must_haves` for `must_have` validated clean and produced zero
  requirements. `extra="forbid"` now, like its five siblings.
- **A child could rewrite an inherited claim while still reading `required`.** Severity
  drop raised `CONTRACT_RELAXATION`; claim/`check_type` substitution did not. Both raise now.
- **The family guard protected one of two doors.** `harness.evaluate` and `pcraft gate` now
  refuse same-family and CLIPScore; the guard is no longer orchestrate-only.
- **A missing tier borrowed another family's threshold band.** Wanted-tier missing is
  SKIPPED, not a silent fall-forward.
- **The tier census reported 1 of 2 next to a green BOUND and exit 0.** Census now gates
  both the exit code and the loop verdict. `pcraft demo` earns `2 of 2`.
- **A mistyped flag exited 2**, the code reserved for a required-atom failure. Usage
  errors are 1.
- **Both generators ignored the conditioning dict** they documented as ControlNet /
  IP-Adapter input. They now refuse if `pose_refs` or `identity_refs` are present.
  Implementing those encoders is separate work.

### Changed

- Suite **105 → 205**. STANDARDS NAMED_COMPENSATORS and EXTERNAL_VERIFIER were scored `2`
  when the public doors were unproven, then restored to `3` when the suite proved both
  doors. Total **17 / 18**.
- Honest status no longer calls the `[image]` generators "unproven by measurement."
  Conditioning is unread. Pose-lock and identity-binding are unimplemented.
- **Inherited `spatial`, `enum`, and `depends_on` are frozen** the same way claim and
  `check_type` already were. Omitting them on a severity raise inherits the base;
  restating them differently is `CONTRACT_RELAXATION`.
- **A `must_have` and a `must_not` may not share an id.** The question DAG keys by
  `atom_id`; a cross-list collision dropped one polarity.
- The installed package now ships `py.typed`.
- **`pcraft bind --contract` is honoured.** The flag was accepted and ignored;
  bind always resolved the demo character.
- The bound-door compensator test now actually reaches ADVANCE (both required
  verifier tiers registered).
- A child cannot neutralize an inherited identity plate (same plate, `method=none`
  / lower weight). Distinct plates still compose.
- `sync-rules` no longer searches cwd first (a planted script would have been exec'd).
- A missing/unreadable gate image escalates through the loop envelope instead of
  escaping `run()`.
- `INPAINT_REGION` varies the seed; regional inpaint is not implemented.
- Device/dtype selection sits inside the classified generator-load try.
- A `select_device` failure no longer becomes `UnboundLocalError` in the load
  handler (`device` is bound to `unset` before the try).
- `pcraft demo` / `bind --mock` print that scores are scripted and pixels were
  not read.
- `GATE_CONDITIONING_UNSUPPORTED` names `identity_ref` / pose spatials, not a
  contract key called `pose_refs`.

## [0.2.1] — 2026-08-18

**The packaging the first release should have carried.**

### Fixed

- **The npm package had no README at all.** `npm/` carried a LICENSE copied across from a sibling
  repo and no README beside it, so the package page rendered blank. npm serves the *latest*
  version's README, which meant even the placeholder's one-line description disappeared the moment
  0.2.0 landed. The package now carries its own README, with the logo as an **absolute** URL —
  npm renders only absolute image URLs, and a repo-relative `<img src>` shows nothing.
- **The PyPI page pointed at a README full of repo-relative links.** The GitHub front door opens
  with a logo at `docs/assets/logo.png` and a seven-language nav bar of sibling files; on PyPI,
  which has no repository around it, all nine of those were broken. `README.pypi.md` carries the
  same content with nothing relative in it, matching the pattern a sibling repo already used.
- **`project.urls` carried only the repository.** Homepage, Documentation, Changelog and Issues
  now resolve from the PyPI sidebar.

### Changed

- Nothing in the package's behaviour. Same 105 tests, same gate, same exit contract.

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
