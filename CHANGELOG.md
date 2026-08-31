# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

A version here marks **a state of the gate** — what it can check, what it refuses, and what it
has never been able to prove. The `[image]` path has now executed once on the 5090
(2026-08-18). The GPU-free core is still the suite.

## [Unreleased]

Health waves over the v1.0.0 surface (dogfood swarm, 2026-08-31): 72 findings fixed across
three amend rounds (Stage A bug/security x2, Stage B proactive x1), suite 394 -> 724.

Stage B round (proactive lens — defensive depth, observability, degradation,
future-proofing; three findings the cross-family panel promoted to CRITICAL):

- **Threshold drift is now detected by value, not by label**: every receipt stamps a content
  hash of the band values alongside `thresholds_version`, and `pcraft replay` asserts both —
  a retune under an unchanged version string flipped verdicts silently before (measured);
  now it raises drift. Legacy receipts without the hash still replay. The CLI passes its
  loaded table through so the check reaches `pcraft replay` users.
- **Tier-0 verdicts are zoned under the instrument that scored**: the router's documented
  SigLIP2 fall-through handed sigmoids to the palette band (a 0.30 strong-match measured
  FAIL end to end); verifier ids now carry their band family and the harness zones by it.
- **A palette enum member that cannot parse as a colour is a named refusal**, not a silent
  drop that narrows the check (one hex typo took the atom off the deterministic verifier
  with nothing recording it).
- A `bound` receipt can no longer be silently clobbered by a later run reusing its
  record id; the CLI's stdio is deliberately UTF-8 (non-ASCII paths crashed or corrupted
  `--json` under locale-derived strict encodings — measured byte-level, fixed through the
  npm launcher too, with an explicit `PYTHONIOENCODING` still winning); `--image-name`
  splits on the LAST `=` so plate names containing `=` parse; a broken `PCRAFT_PYTHON` is
  a loud error instead of a silent PATH fallback, and `pcraft doctor` names the
  interpreter it ran under.
- `extends` cycles and runaway depth are refused at validate with named codes (the fourth
  appearance of the graph-integrity class, now closed on both mechanisms); `CONTRACT_INVALID`
  aggregates every field error instead of the first; blank `claim`s are refused at
  construction like blank ids; duplicate plugin registration is a named refusal.
- The injected-predictor synth path runs the same anti-prose-dump guard as the default
  path (a fabricated coverage map sailed through before).
- Oversized images are measured in O(1) memory (587.8 MB -> 5.73 MB on the same input)
  instead of capped in a way that would have reopened the padding hole.
- Dependency schedule protection: `pillow<14` (Image.getdata removal, 2027-10) with a
  `getattr` migration shim already in place, `pydantic<3` — both with evidence-carrying
  comments; all eleven GitHub Action pins moved off the deprecated Node20 runtime with
  each target major's runtime verified.

Earlier rounds follow. The recurring shape, again: checks that read as live
while checking less than they appear — this time including one on the bind door itself.

Second-round fixes (composed-surface re-audit findings — seams between the first round's
fixes):

- **The recipe door now refuses an identity method it cannot apply** (`pcraft recipe` on a
  contract declaring `method=ip_adapter` exits 2 with `GATE_CONDITIONING_UNSUPPORTED` and a
  hint naming `method=reference`), instead of silently stamping the plate into the Cloud
  stitch as if the declared lock applied. The shipped example contract declares SDXL
  methods, so the bare quick-start `pcraft recipe` now demonstrates the refusal; a
  reference-method shipped example is queued as follow-up work.
- A `depends_on` **cycle** is refused at validate/load (`CONTRACT_CYCLIC_DEPENDS_ON`, exit
  1, self-edges included) instead of passing `pcraft validate` and dying downstream in a
  bare `ValueError`; the referential guard moved onto the model so every construction path
  is covered, and the harness fails closed if a cycle arrives by construction anyway.
- The **Pillow decode branch** gets the same declared-vs-decoded pixel-count refusal the
  stdlib fallback got in round one — a truncated file scored a confident palette verdict on
  short data in the branch that runs in production.
- A nonexistent `--fill-mask` path is refused with a named input error instead of writing a
  Cloud graph with the bracer refusal silently disabled.
- The cp437/ASCII sweep reached the strings round one missed: the escalation checkpoint
  text (which crashed at the exact moment a human checkpoint should display), a Flux hint,
  and every remaining user-facing string in gate/loop/domain files — pinned by
  AST-sweep encodability tests per domain.
- A bare Ctrl-C exiting **130** (128+SIGINT) is now a documented, test-pinned convention
  (STABILITY.md), deliberately outside the 0-4 table — folding it into exit 1 would leave a
  script unable to tell a typo from an interrupt.
- `Tier0Router` reports the delegate that actually scored (`palette.hist.v1`) as its
  verifier id on verdicts and receipts, matching what round one's provenance fix intended.
- Five public surfaces quoting the pre-wave test count were refreshed to the measured
  suite; the count-pinned-in-prose habit is now called out in the operating docs.

First-round entries follow.

### Added

- `pcraft doctor` reports version coherence: installed distribution metadata vs the tree's
  declared version, loudly, on the box where stale editable dist-info has now bitten three
  times. `pcraft --version` warns on stderr when the mismatch is detectable; stdout stays
  the bare version line.
- The kontext recipe receipt computes `do_not_mask_bracer` (`bool | None`) instead of
  asserting a hardcoded `True` nothing checked; `None` is the honest answer for a
  caller-painted mask, and the terminal banner now tracks the receipt.

### Fixed

- **A dangling `depends_on` can no longer flip escalate into bind.** The loader refuses a
  contract whose `depends_on` names no atom (`CONTRACT_UNKNOWN_DEPENDS_ON`, exit 1), and
  the harness fails closed (SKIPPED, never PASS) if one still arrives by construction.
  Measured before the fix: a one-character typo in the shipped example turned
  AMEND/escalate into ADVANCE/bind with a clean census and exit 0.
- **An unknown `identity_ref.method` can no longer silently drop the identity lock while
  the receipt stamps the plate.** The dead deny-list (an empty frozenset) is now an
  allow-list refusing on both generate paths; `assemble()` honors `method` instead of
  bucketing every plate by scope; Flux refuses a wrong-family lock before writing a recipe.
- The stdlib PNG fallback refuses (`RUNTIME_VERIFIER_CALL_FAILED`) when it decodes fewer
  pixels than the header declares, instead of scoring a fraction of the image with
  confidence.
- Malformed contracts and pinned artifacts raise the documented error shape
  (`CONTRACT_INVALID` exit 1 / `IO_ARTIFACT_INVALID`) instead of leaking a raw pydantic
  `ValidationError` as a crash (exit 2) — the covered exit-code table now holds at both
  doors.
- `pcraft replay` on a receipt from a newer prompt-craft exits **1** with an upgrade hint,
  matching its contract sibling (`CONTRACT_SCHEMA_UNSUPPORTED`); it briefly exited 2 in
  v1.0.0. STABILITY.md names the per-code override.
- The release workflow's tag==version gate now runs on every trigger standing on a tag —
  `workflow_dispatch` runs skipped the exact check built after two stale-version releases.
  Statically validated; a live dispatch run remains to be observed.
- The bind door (`bind --no-mock`) checks the full `[image]` extra including
  `transformers`, from one source of truth shared with `doctor`, so an incomplete
  environment refuses cleanly (`DEP_IMAGE_MISSING`) instead of crashing deep in the
  pipeline.
- Every user-facing string in the CLI, errors, and contract layers is pure ASCII, pinned
  by cp437-encode tests: em dashes in help text crashed `pcraft --help` outright under the
  default `cmd.exe` codepage, and the same class sat in live refusal hints.
- Compiled-artifact ids are collision-free across distinct compiles (content fingerprint;
  `_next_version` returned a constant per optimizer).
- Failed generate attempts are recorded on the receipt with their real error chained into
  `RUNTIME_GENERATE_EXHAUSTED` (previously discarded whole — a diagnostic dead end that
  destroyed the `DEP_IMAGE_MISSING` hint on the exact path where it was the answer), and
  missing-dependency failures are no longer retried.
- `LoopConfig.thresholds_version` is a live assertion (`CONFIG_THRESHOLDS_INVALID` on
  mismatch with the table) instead of a knob nothing read.
- Tier0Router names the instrument that actually scored (`last_delegate`), and text-enum
  atoms fall through to SigLIP2 as its docstring always claimed.
- The stability-surface test now guards drift in both directions (document -> test), pins
  `Verifier` and the `code`/`message`/`hint` shape, and the verify gate's `-O` leg carries
  the reachability pin every other leg already had.
- Atom/MustNot/Contract ids require `min_length=1`, closing the surviving mutant's
  equivalence argument at the root; `_severity_rank()` raises a named refusal instead of
  `KeyError` on an unknown severity.
- Registry long-descriptions and the operating docs no longer assert the retired pre-1.0
  position against a shipped v1.0.0: README.pypi.md and npm/README.md carry the
  interfaces-not-pictures paragraph (reaches the registries at the next publish), and
  grok.md / AGENTS.md / ADVISOR.md / HANDOFF.md / SHIP_GATE.md fences read 1.0.0.

### Changed

- `IO_RECORD_SCHEMA_UNSUPPORTED` exit code: 2 -> 1 (see Fixed; documented as a deliberate
  per-code override in STABILITY.md, aligned in the first patch after v1.0.0 before any
  minor shipped).

## [1.0.0] — 2026-08-18

**The interfaces are stable. The pictures are not finished, and the two are different claims.**

The pre-1.0 ruling was *"a generate that ran is not a stability claim."* It reached the right
answer from the wrong premise: it argued from **capability**, and capability is exactly the
category that does not block a stable interface — it improves in minor releases. Held only by
that argument, the position weakened every time a capability landed, which is why it kept
resurfacing.

The real blockers were three markers that read as compatibility checks and were never
compared. None of them appeared on the honest-status table, because none of them were about
the pictures. All three are closed below.

### Added

- **`STABILITY.md`** — what semver covers and, at equal length, what it does not. Covered: the
  CLI commands, the exit-code contract (including `4` for could-not-run, which exists so a CI
  branch cannot read "the gate ran and failed" when the gate never ran), the listed import
  paths, and the two on-disk formats. **Excluded, by name:** threshold table *values*, the
  identity sub-gate, `core.optimize`, and everything under `subdomains/sprite`.

  The identity sub-gate is named **provisional and out of scope**, with `0.55` / `0.05` stated
  as **unvalidated defaults** — never calibrated against a labelled holdout, bare constructor
  arguments in no table and no receipt. That excludes it from the promise without deleting,
  promoting, or wiring it. A holdout is work that belongs before the sub-gate is *wired*, not
  before the package is *stable*.

  Every name in the document is checked by `tests/test_stability_surface_names_resolve.py` —
  it parses the file rather than restating it, so the two cannot drift. It caught a wrong
  module path in the document on its first run.

- **`AssetRecord.schema_version`, and a `load()` that branches on it.** The receipt reader was
  fail-closed in **both** directions (`extra="forbid"` rejects an added field; a required field
  rejects a dropped one), so any future record change would have invalidated every receipt
  already on disk, with no migration path. `replay` reads receipts written by earlier runs, so
  this was a live liability, not a hypothetical one. A receipt with no `schema_version` is read
  as v1 — that is how every receipt written before 1.0.0 keeps working — and an unknown version
  raises **`IO_RECORD_SCHEMA_UNSUPPORTED`**, deliberately *not* `IO_RECORD_INVALID`: "written by
  a newer prompt-craft" is not "corrupt", and collapsing them would send someone off re-binding
  a perfectly good file.

- **`Development Status :: 5 - Production/Stable`** and the rest of the PyPI classifiers, which
  the package had never carried.

### Changed

- **The contract `$schema` is enforced.** `prompt-craft/contract.v99-NONSENSE` used to load
  without complaint — a file could announce a format nobody supports and be parsed as though it
  had announced nothing. Unsupported values now raise **`CONTRACT_SCHEMA_UNSUPPORTED`** (exit 1,
  user input). A version marker that is never compared is worse than no marker: it reads as a
  compatibility check to everyone who sees it in the file.

- **`replay` asserts `thresholds_version`.** The receipt has always stamped the table version
  and nothing ever compared it, so replaying under a retuned table silently re-decided and
  reported success. `pcraft replay` now loads the table and refuses on drift, naming both
  versions. The parameter is **keyword-only with no default** — passing `None` still skips the
  comparison, but a caller has to say so, which is the difference between a decision and an
  oversight. `--skip-threshold-check` states it out loud, and the summary line then reads
  `thresholds=NOT CHECKED` rather than staying quiet.

- **The pre-1.0 test flipped rather than vanished.** `test_version_is_pre_one_and_the_readme_agrees`
  asserted the major was `0` and said promoting "needs an evidence-backed decision, not a test
  edit." This release is that decision; its successor asserts 1.x does not silently regress,
  that the README tracks the version, and that `STABILITY.md` and the stable classifier ship
  together — because `1.0.0` without the document is a number, not a commitment.

Suite **394** (was 359), GPU-free and deterministic.

## [0.4.0] — 2026-08-18

**The gate started reporting on itself. Everything it found, it found about its own
honesty rather than about the pipeline.**

Nothing in the image path changed in this release. What changed is that four checks
which read as live were doing less than they appeared to: a lint rule set inherited from
whatever tool version resolved, a `# type: ignore` that stopped applying when a formatter
wrapped its import, a success token that did not name its own scope, and a gate that
linted every file except the one defining the gate. The version moves because `verify.py`
gained a flag and two legs, not because the pipeline proved anything new.

### Added

- **`verify.py --audit` -- the dependency audit as an opt-in leg, with three outcomes
  rather than two.** `verify.py` and CI previously disagreed about what "verified" means;
  this gives them one definition. It stays **off by default**, and not out of squeamishness
  about the network: running it makes the gate *time-varying*, so the same tree passes
  today and fails tomorrow when an advisory publishes. Correct for CI, wrong for a release
  gate, which should be a function of the tree.

  The three outcomes exist because two would have shipped a gate that is red forever:

  | outcome | example on this rig | behaviour |
  |---|---|---|
  | advisory **with** a published fix | `setuptools 78.1.0` -> 83.0.0 | **fails** -- actionable |
  | advisory with **no** published fix | `diskcache 5.6.3` PYSEC-2026-2447 | reported, does not fail |
  | **could not audit at all** | `torch 2.13.0+cu130` -- a local build, not on PyPI | reported loudest |

  The middle row is why: `diskcache` arrives transitively from `dspy` under `[synth]`, has
  no version to upgrade to, and CI never sees it because CI installs `[dev]` only. Failing
  on it would have made `--audit` permanently red on the blessed box with no move
  available, which is how people learn to skip gates. The third row is the one that would
  otherwise pass silently: with `[image]` installed, pip-audit cannot see the largest
  dependency in the tree, and a report that said "no vulnerabilities" would be printing
  "could not check" as "checked clean".

  Each run also **names the extras it resolved against**, because the verdict depends on
  that set -- `[synth]` surfaces an advisory `[dev]` does not. Without it two honest runs
  on different boxes disagree and neither can be trusted, which is the `ruff --select`
  override trap in a different tool. A passing run carrying caveats prints `QUALIFIED`
  rather than a bare OK. Duplicate advisory rows (pip-audit emits them) are deduped, and a
  missing or unparseable report **refuses** rather than reporting an audit that did not
  run. Twelve tests, all offline against synthetic reports.

- **`verify.py` declares its own scope, and asserts the installed version matches the
  tree.** Two legs from one finding: the gate's closing output was a bare `VERIFY OK`, a
  success token that does not name what it covers -- and its coverage is smaller than it
  reads.

  - The summary now prints `VERIFY OK -- checked: <the legs that actually ran>`, followed
    by `NOT CHECKED -- dependency audit`, naming CI's separate `pip-audit` step. The leg
    list is accumulated as legs pass rather than hard-coded, and is threaded through each
    `main()` call rather than held at module level, so the summary cannot drift from what
    ran in either direction -- neither naming a leg that did not run, nor carrying one in
    from a previous invocation in the same process. This is the visible-skip doctrine `ci.yml` already argues for under
    `--skip-editable`, turned on the gate itself: "could not check" must never read as
    "checked clean".
  - **Version coherence**, under `--installed`: the installed distribution's version must
    equal `pyproject.toml`'s, or the gate refuses and names both numbers. It runs first --
    an environment lying about its version should not be discovered after a full suite and
    two builds. `_declared_version()` reads the file rather than importing the package;
    importing would compare installed metadata against installed metadata, agree with
    itself, and pass hardest in exactly the case it was written for.

  This pins a defect that has now happened twice: `f23f345`, and again on 2026-08-18, when
  the blessed `.venv` reported **0.2.1 against a 0.3.0 tree** through an entire session
  while every gate stayed green. `package_version()` falls back to the tree literal *only*
  on `PackageNotFoundError`, so stale metadata is *found* and the wrong version returns
  silently. The suite could not catch it -- the quick-count recipe sets `PYTHONPATH=src`
  while the metadata read ignores `PYTHONPATH` entirely. The gate and the lie were looking
  at different things. Suite **359**, up from 339.

### Fixed

- **CI `verify (3.11)` was red at `dependency audit`, and had simply never been fixed.** The
  3.11 leg gets a bundled setuptools from `ensurepip` (79.0.1, carrying PYSEC-2026-3447);
  3.12+ stopped bundling it, which is the whole reason 3.13 audited clean and 3.11 did not.
  setuptools is **not a declared dependency of this package** — pip-audit audits the
  environment, not the dependency set, so the leg failed on something `pyproject.toml` never
  asked for. The audit step now installs `setuptools>=83` alongside pip-audit.
  `--ignore-vuln PYSEC-2026-3447` was available and was refused: it makes the step green by
  lowering the gate. The cost is symmetric and is named in the workflow rather than left to be
  noticed — on 3.13 this *installs* a setuptools that was not there before, which is harmless
  and keeps the two legs identical instead of conditionally different. Not a regression from
  the lint widening; the identical failure is present on run `32194862049`. Reproduced and
  fixed in a CI-equivalent 3.11.15 venv (79.0.1 ambient, matching the runner) before landing.

- **A `# type: ignore` that had silently stopped applying.** Adopting isort wrapped the
  `click.exceptions` fallback import in parentheses and left its
  `# type: ignore[assignment,no-redef]` on the inner line, where mypy does not apply it. The
  suppression still looked live and was not — the exact defect class this gate exists to
  catch. The ignore now sits on the statement's first line with a comment saying why it must
  stay there. Caught by mypy 2.3.1 in a CI-equivalent venv; the local box (mypy 2.1.0,
  ruff 0.15.16) does not produce this wrap at all.
- `_merge_atoms_fail_closed` rebuilt its `{b.id for b in base_atoms}` set once per child atom.
  Hoisted out of the loop — the same merge, no longer quadratic. (Surfaced by PERF401.)

### Changed

- **The gate now checks the file that defines the gate.** `lint` ran `src tests` and
  `typecheck` ran `src`, so `verify.py` was the one file exempt from the checks it runs on
  everything else -- and a pre-existing `PLW1510` sat unreported in `_run` because of it.
  The targets are now `ruff check src tests verify.py` and `mypy src verify.py`; mypy goes
  from 56 to 57 files, with no conflict against the pinned `packages = ["pcraft"]`.

  Closed while both tools were already clean on it, which is the only cheap moment to
  close such a thing -- `verify.py` has grown from a thin runner into a file with JSON
  parsing and category logic, exactly the code a gate exists for. This is the fourth
  appearance of one shape in this repo: `[tool.ruff]` with no `select`, a bare
  `VERIFY OK`, mypy aborting on a numpy stub while still reading as configured, and now
  the gate exempting itself.

- **The lint gate now declares what it lints for.** v0.3.0 pinned the historical default set
  (`E4/E7/E9/F`) to buy a clean release; it did not decide the rule set. `[tool.ruff.lint]`
  now selects 15 families and carries an `ignore` list where **every entry names the reason it
  is rejected**. 64 findings resolved; suite **339**, unchanged.

  Adopted: `A`, `B`, `BLE`, `C4`, `FURB`, `I`, `N`, `PERF`, `PL`, `PTH`, `RUF`, `SIM`, `TRY`,
  `UP`, on top of `E4/E7/E9/F`. Two of these were free — with `B008` excluded **bugbear finds
  nothing**, and `A` finds nothing beyond one shadow (`compile`) that is the command's own
  name and already suppressed.

  Rejected, with the reason recorded beside each ignore: `B008` (every one is the
  `typer.Option(...)` idiom Typer requires), `PLC0415` (119 deliberate in-body imports that
  keep `core/` free of torch symbols — the property `test_core_is_gpu_free.py` defends),
  `PLR2004` (52 of 58 are tests asserting literals), `PLR0913/0917/0915/0912` (arbitrary
  counters against deliberate protocol signatures), `TRY003` (would dismantle
  `PromptCraftError(code, message, hint)` and its exit-code contract), `TRY301` (the
  raise-inside-try is how `typer.Exit` routes past the blind-except backstop). Not selected at
  all, with reasons in the config header: `ARG` (47, protocol conformance), `EM` (99),
  `D` (536), `S` (763), `ANN` (878).

- `BLE` is selected rather than globally ignored. 11 blind-except sites already carried a
  per-site `# noqa: BLE001`; the 3 that did not now carry one naming its own reason. A global
  ignore would have made all 14 markers dead and stripped them. The rule stays live for new
  code.

- Eight `class X(str, Enum)` are now `StrEnum` (`UP042`). Verified before adopting: `json.dumps`
  output is **byte-identical** either way, so no record or artifact changes shape; only
  `str()`/f-string rendering differs and `src/` has no such site. Confirmed on both CI legs.

- `RUF100` was evaluated **last**, after the select was locked, and the kickoff's numbers were
  corrected in the process. Measuring a family with `--select RUF` (or `--select RUF100`)
  **overrides the config's select**, so every suppression for a non-selected rule reads as
  dead: the same tree reports **27** that way and **2** against the actual gate. Both real ones
  were `# noqa: F401` on an `import torch` that is used. Measure RUF100 with a bare
  `ruff check`, never with `--select`.

## [0.3.0] — 2026-08-18

**The encoders landed and a 5090 ran them. The frame did not carry the plate, and the
typecheck had stopped checking.**

Every conditioning encoder the contract could express is now wired and covered. Two of them
were run for real rather than mocked, and both live runs are recorded with what they failed
to do. The suite went 105 -> 338 across the swarm; the version stays pre-1.0 because a
generate that ran is not a stability claim.

### Fixed

- **The lint gate's meaning was inherited, not declared.** `[tool.ruff]` set no `select`, so
  ruff linted against whatever DEFAULT rule set the resolved version carried. Local 0.15.16
  passed clean; CI resolved 0.16.3 from an unbounded `ruff>=0.6` and produced 62 errors on
  identical code, failing this release at the verify gate. The 0.16 defaults are not simply
  stricter — 19 of the 62 were `B008` (call in an argument default), which is the *required*
  Typer idiom, and 3 were `BLE001` on `except Exception` blocks that already carry a
  deliberate `# noqa`. `[tool.ruff.lint] select` now pins the historical set the tree has
  always passed, and `ruff` is upper-bounded so the tool cannot move under a gate that can
  block a publish. Verified against both 0.15.16 and 0.16.3. Widening the rule set (isort,
  bugbear, refurb) is a real cleanup, to be done deliberately rather than inside a release.

### Measured

- **Local 5090 SDXL `generate()` ran** (2026-08-18). CUDA
  `torch 2.13.0+cu130`, RTX 5090, 31.84 GB. Ashen-reaver with the
  shipped two-hand OpenPose + identity plate (`method=ip_adapter`),
  seed `169405236028824`, kind `controlnet_ip`. Looked at the frame:
  orcish face with tusks; crossed arms, not a two-hand axe; no
  triple-bar sigil; no bone-spike bracer. Two IP-Adapter plates on
  one adapter refuse (`Cannot assign 2 scale_configs to 1
  IP-Adapter`). `bind --no-mock` still raises `DEP_IMAGE_MISSING`.
  Flux text-only / Fill not run — weights not on disk.
- Suite **337 → 338** after the 3.11 CI floor pin.
- Suite **332 → 337** after Phase 9 (typecheck restored, `verify.py` legs).
- Suite **328 → 332** after two-plate IP-Adapter + live `bind --no-mock`.
- Suite **325 → 328** after the GEPA pin and the extra-installed test doors.
- **Live GEPA compile ran** (2026-08-18) on local Ollama `hermes3:8b`.
  600B was not up; this is not a 600B run. `compile_synthesizer` with
  an external `gate_metric` (required-atom coverage minus a CLIP
  overflow penalty) pinned `sprite.synth.v1-gepa.json`
  (`generated_by=gepa`). Seed `sprite.synth.v1.json` is untouched.
  `pcraft compile` still raises `STATE_COMPILE_NEEDS_GATE`.
  DSPy 3.3 GEPA requires a configured reflection LM; the runner now
  passes `dspy.settings.lm` instead of asserting.

### Fixed

- **The typecheck was a gate that could not run.** `[tool.mypy]` targeted the
  declared 3.11 floor, but the `[image]` extra pulls numpy 2.5, whose bundled
  stubs use PEP 695 `type X = ...` (3.12+). mypy refused to parse them and
  aborted with "errors prevented further checking" — so from the moment
  `[image]` was installed it checked **zero** pcraft files while still reading
  as a configured gate. It was hiding 7 real errors. Per-module
  `follow_imports = "skip"` does not help; the failure is at parse time, before
  module policy applies (verified against a cleared cache). `python_version` is
  now `3.12`. **Named cost:** mypy no longer catches 3.12-only syntax that would
  break on the 3.11 floor, and CI runs 3.13 only — so `requires-python = ">=3.11"`
  is currently asserted by metadata and verified by no gate. Closing that needs a
  3.11 CI leg or a raised floor; it is not closed here.
- **The 7 errors the dead typecheck was hiding.** `run_mock_loop` unpacked the
  loaded `ThresholdTable` back over its own `thresholds: Path | None` parameter,
  so one name meant two types (runtime was correct; the annotation was not, and
  `run_live_loop` beside it already spelled this right). `_UNIMPLEMENTED_METHODS`
  was an unannotated empty `frozenset()`. The typer/click portability fallback
  binds two structurally distinct exception classes to one name, which is the
  point of the fallback — now marked rather than left as noise.
- **`verify.py` runs the gates the project configures.** `ruff` and `mypy` were
  configured in pyproject and invoked by no workflow and no script, which is how
  the typecheck went inert unnoticed. Both are now hard legs, ordered before the
  suite so a type error does not queue behind a full run plus two builds. Both
  already ship in the `[dev]` extra the script documents, so this adds no
  dependency.
- **The 3.11 floor is now a CI leg, not metadata.** `requires-python`
  stays `>=3.11`. CI runs 3.11 and 3.13 on the core + `[dev]` extra.
  The `[image]` extra (numpy 2.5) is not claimed on 3.11. Floor was
  not raised: we had never measured 3.11, and dropping the promise
  would have hidden that.
- **Two IP-Adapter plates stay on one adapter.** Costume + face
  images are all passed. One `load_ip_adapter` takes one scale (the
  strongest requested lock). The assembled ashen-reaver contract
  can generate. Do not drop a plate.
- **`bind --no-mock` is the live door.** Missing `[image]` is still
  `DEP_IMAGE_MISSING`. When the extra is present, the loop uses
  `SDXLGenerator` + plugin verifiers, not the stub. `--mock` is
  unchanged.
- **The GPU-free suite stays GPU-free when `[image]` is installed.**
  Three tests used `DEP_IMAGE_MISSING` as a proxy for "fell through to
  `_load`" and then ran a live 30-step SDXL generate once torch was
  present. They now stub `_load`. The torch-absence canaries accept a
  real `site-packages` torch. Tests that assumed `[synth]` was missing
  now force that door so a live DSPy install cannot launch GEPA.

### Added

- `tests/test_verify_legs.py` — pins gate **reachability**, not gate cleanliness:
  every `[tool.*]` quality gate configured in pyproject must be invoked by a
  `verify.py` leg. Reads verify.py's own AST (resolving the suite leg's
  `pytest = [...]` variable, and ordering by `lineno` rather than `ast.walk`
  order). Asserting "mypy is clean" here would have been the wrong test — it
  would still pass if someone deleted the leg. Verified red: removing the
  typecheck leg fails both the reachability and the ordering assertions.
- **`--json`** on `synth`, `gate`, `bind`, `demo`, `replay`, `list`, and `validate`.
  The pydantic model is the stdout document; the human banner moves to stderr.
- **`--version`** and **`pcraft doctor`**. Doctor reports python, `[image]`/`[synth]`
  extras, and whether the contract store (plus threshold table) loads. GPU-free.
- The gate **rejects NaN / non-finite / out-of-range verifier scores** as SKIPPED
  instead of zoning them. A crashing `score()` is the same, not a traceback.
- **Band invariants:** `high >= low`, both in `[0, 1]`. The thresholds version
  rides the gate transcript. An inverted table is `CONFIG_THRESHOLDS_INVALID`.
- The **repair ladder is not run** when the transcript is unrepairable
  (`UNAVAILABLE`, no required score, or a short tier census).
- **SDXL pose-lock** via ControlNet OpenPose. A missing pose plate is
  `GATE_CONDITIONING_REF_MISSING`, not a silent txt2img. Flux still refuses
  (unmeasured).
- **SDXL IP-Adapter** identity-bind for `method=ip_adapter`. `lora` /
  `instantid` still refuse. `method=none` skips the plate.
- **`INPAINT_REGION` is a real inpaint.** Same seed, region mask, previous
  image in `inpaint_from`. The stub writes `stub_seed{N}_inpaint.png` so
  the named action is not a byte-identical regenerate.
- **Shipped plates.** OpenPose maps (two-hand weapon + 8-view turnaround)
  are drawn as BODY_25 ControlNet maps. Identity plates for ashen-reaver
  (face) and ashen-pact (costume) ship under the sprite subdomain.
  Contract refs resolve against that tree, not cwd. The example faction
  plate is `method=ip_adapter` so both plates can actually bind.
- **Palette histogram** at Tier-0 for hex `enum` colours. Text enums still
  SKIP (they belong to SigLIP2). A taupe studio backdrop is not required
  to live inside the palette.
- **Reference lock pack.** Identity + OpenPose in one reference-conditioned
  edit moved the axe to a two-hand grip. Identity + costume did not move
  pose. `method=reference` is reserved for that Cloud/Imagine path.
- **`pcraft recipe`** emits the measured Cloud graph: Kontext stitch
  (identity + OpenPose), in-graph left crop so the diptych never ships,
  then Flux Fill on a fist-only mask. Do not mask the bracer.
  `method=reference` is this path; SDXL refuses it. Does not submit.
- **RESYNTH rewrites the prompt.** Failed atoms are front-loaded and the
  synthesizer runs again. A seed bump alone is not a re-synthesize.
- **Contrastive human checkpoint.** Escalation is "you probably thought X;
  I chose Y" per flagged atom, not a zone name. STANDARDS #5 is now 3.
- **Receipts store the attempt story.** Each generate+gate step (seed,
  zone, repair) rides the record, not just `retry_count`.
- **`pcraft schema`** dumps JSON Schema for the authoring contract.
- **`MustNot` accepts `spatial`.** A negation can name a region. The
  compiled question carries it. Inherited spatial is frozen the same
  way enum already was.
- **Cloud math slots are dotted.** `ComfyMathExpression` uses
  `values.a`, not a nested map. Nested form dry-ran and 400'd live.
  `--image-name local=cloud` remaps LoadImage to an uploaded plate.
- **Tier-2 is a real DSG.** The atom expands into entity / attribute /
  relation probes. A missing entity skips dependents. The QG slot is
  read (template by default). The answerer may still share Tier-1's
  VQAScore weights; that sharing stays on `shares_model_with`.
- **Offline GEPA + `DSPySynthesizer`.** `compile_synthesizer` pins a
  program against an EXTERNAL gate metric (`dspy.GEPA` by default;
  inject a runner in tests). `DSPySynthesizer` runs the pinned
  artifact and refuses to silently become `TemplateSynthesizer`.
  The CLI does not generate pixels (`STATE_COMPILE_NEEDS_GATE`).
  Never on the per-asset hot path.

### Changed

- **Public surfaces match the measured tree.** README, handbook, landing,
  PyPI README, and npm README no longer claim 205 tests or that
  pose-lock is unimplemented. The Starlight title is `prompt-craft`,
  not `my-package`. The landing badge is v0.2.1.
- **`grok.md`** is the solo-seat operating file. `AGENTS.md` points at
  it so the harness loads it.
- **Flux Fill inpaint** is wired (fake-torch). `method=reference` writes
  the Cloud recipe and raises `GATE_CLOUD_SUBMIT` instead of pretending
  Kontext ran locally. Pose / IP-Adapter stay refused on Flux.
- **`method=lora` on SDXL.** `load_lora_weights` + adapter scale. The
  plate is a weights file, not an image. Missing file is
  `GATE_CONDITIONING_REF_MISSING`. Flux still refuses LoRA.
- **`method=instantid` on SDXL.** InstantX ControlNet + face plate.
  InstantID and IP-Adapter cannot share one generate. Flux refuses.
- **`grok.md` / `HANDOFF.md` / `CONTRIBUTORS.md`.** Solo-seat
  operating file, next-session brief (live 5090 generate + live
  GEPA), Grok listed as a contributor.

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
- **`--contracts-dir` / `--thresholds`** on synth, gate, bind, and replay.
  `pcraft list` and `pcraft validate` added. An empty custom store is
  `INPUT_EMPTY_STORE`, not a silent fall-back to ashen-reaver.

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
