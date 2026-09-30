# prompt-craft: how it works

Mapped at 2026-09-30 from commit 43f3cfe by Atlas 1.24.0.

## What this is

8 parts, mostly Python (112 files), CSS (2), JavaScript (2), TypeScript (2) and Astro (1). Work enters through 5 doors; the busiest is release, which reaches 5 parts. It publishes to PyPI and @mcptoolshop/prompt-crafter to npm. It deploys a site to GitHub Pages. People run pcraft.

## What changed since 2026-09-25 (cdc0bed)

- ci's pull request trigger now also names `codecov.yml`.
- ci's push trigger now also names `codecov.yml`.
- ci now also runs tests/.
- And 4 more changes to doors.
- src/pcraft/domains/image/subdomains/sprite/poses/turnaround/ is now written by scripts/draw_openpose_plates.py.
- src/pcraft/domains/image/subdomains/sprite/poses/two-hand-weapon.openpose.png is now written by scripts/draw_openpose_plates.py.
- src was authored and is now mixed.
- 1 file added and 3 changed content, across 2 parts.

## What comes in

1. **release.** When a release is published; or by hand. Runs tests/ and verify.py; checks src/. On a run by hand with dry_run false, it also runs npm/bin/pcraft.mjs.
2. **ci.** On a pull request touching 10 paths; on a push touching 10 paths; or by hand. Runs tests/ and verify.py; checks src/.
3. **Deploy site to GitHub Pages.** On a push to main touching 2 paths; or by hand. Runs site/astro.config.mjs and site/src/.
4. **pcraft** (a command people run, from pyproject.toml). Runs src/pcraft/cli/__init__.py.
5. **pcraft** (a command people run, from npm/package.json). Runs npm/bin/pcraft.mjs.

## What happens through release

1. The workflow runs verify.py in the repository root and tests/ in tests; it checks src/ in src.
2. On a run by hand with dry_run false, it also runs npm/bin/pcraft.mjs.
3. That reaches scripts (3 files).
4. It publishes to PyPI and @mcptoolshop/prompt-crafter to npm (on a run by hand, only with dry_run false).

## Who reads the results

release writes nothing this map can see.

## The other doors

**ci** runs tests/ and verify.py, checks src/, reaches scripts, and uploads coverage to Codecov.

**Deploy site to GitHub Pages** runs site/astro.config.mjs and site/src/, and deploys the site.

**pcraft** (a command people run, from pyproject.toml) runs src/pcraft/cli/__init__.py and reaches scripts.

**pcraft** (a command people run, from npm/package.json) runs npm/bin/pcraft.mjs.

## What breaks what

- **scripts** is imported by 1 part (src), and by 1 more only from tests; it sits on the path of 3 doors.
- **src** is imported by 1 part (scripts), and by 1 more only from tests; it sits on the path of 3 doors.
- **tests** is run as a child process by 2 parts (the repository root, scripts) and sits on the path of 2 doors.
- **the repository root** is imported only from tests, by 1 part (tests), and sits on the path of 2 doors.
- **npm** is imported by no other part and sits on the path of 2 doors.

## What tends to change together

- **src/pcraft/core/receipt/asset_record.py** and **tests/test_receipt_replay.py** changed together in 6 of 7 commits, and the tests part imports the src part.
- **src/pcraft/core/gate/checkpoint.py** and **tests/test_feat_checkpoint.py** changed together in 5 of 7 commits, and the tests part imports the src part.
- **tests/test_verify_legs.py** and **verify.py** changed together in 7 of 10 commits, and the tests part imports the repository root.
- **src/pcraft/core/contract/loader.py** and **tests/test_amend_contract.py** changed together in 8 of 12 commits, and the tests part imports the src part.
- **src/pcraft/core/gate/exit_contract.py** and **tests/test_gate_exit.py** changed together in 6 of 9 commits, and the tests part imports the src part.

1 file changed together with its own test, as expected.

Confidence is low: fewer than 25 source files reach 10 revisions in the window.

Window: 180 days; a pair counts from 3 shared commits, since 12 source files reach 10 revisions; the floor rises to 10 when 25 do.

## What no test touches

Every code part is touched by at least one test.

npm is tested only by its package's own test script, which a workflow runs.

## Written but never read

- **src/pcraft/domains/image/subdomains/sprite/poses/turnaround/** is written by scripts/draw_openpose_plates.py and read by nothing else in this repository.
- **src/pcraft/domains/image/subdomains/sprite/poses/two-hand-weapon.openpose.png** is written by scripts/draw_openpose_plates.py and read by nothing else in this repository.

## Helpers that look duplicated

No two parts export a helper that looks alike.

## Generated, never hand-edited

- **src/pcraft/domains/image/subdomains/sprite/poses/turnaround/** is written by scripts/draw_openpose_plates.py.
- **src/pcraft/domains/image/subdomains/sprite/poses/two-hand-weapon.openpose.png** is written by scripts/draw_openpose_plates.py.

## Hand-authored

People write .github/, docs/, the repository root and site/; 5 writes with paths built at run time may land here.

## Where to start

src/pcraft/cli/__init__.py → scripts/sync_rules_from_readouts.py

Read those in order to follow one run of pcraft end to end. This path follows pcraft (a command people run, from pyproject.toml) from its entry, since ci runs only tests, scripts that import no code here and checks.

## What this map cannot see

- 8 imports could not be resolved: `src/pcraft/domains/image/scaffold.py` imports a path built at run time; `src/pcraft/domains/image/subdomains/sprite/calibrate.py` imports a path built at run time; `tests/test_amend_cli.py` imports a path built at run time; and 5 more.
- 5 writes and 4 reads use paths built at run time and are not named here.
- 9 writes and 22 reads go to a path their caller passes, not to this repository.
- 1 read goes to a temporary directory, not to this repository.
- 2 commands are built at run time and not followed.
- Statistics confidence is low: fewer than 25 source files reach 10 revisions in the window.

Regenerate with `npx --yes @dogfood-lab/atlas map`.
