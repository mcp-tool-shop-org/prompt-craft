# prompt-craft: how it works

Mapped at 2026-09-25 from commit cdc0bed.

## What this is

8 parts, mostly Python (112 files), JavaScript (2) and TypeScript (2). Work enters through 4 doors; the busiest is release, which reaches 4 parts. It publishes to PyPI and @mcptoolshop/prompt-crafter (npm) to npm. People run pcraft.

## What changed since the last map

This is the first map.

## What comes in

1. **release.** When a release is published; or by hand. Runs verify.py; checks src/pcraft/. On a run by hand with dry_run false, it also runs npm/bin/pcraft.mjs.
2. **ci.** On a pull request touching 9 paths; on a push touching 9 paths; or by hand. Runs verify.py.
3. **Deploy site to GitHub Pages.** On a push to main touching 2 paths; or by hand. Runs site/astro.config.mjs and site/src/.
4. **pcraft** (a command people run). Runs src/pcraft/cli/__init__.py.

## What happens through release

1. The workflow runs verify.py in the repository root; it checks src/pcraft/ in src.
2. On a run by hand with dry_run false, it also runs npm/bin/pcraft.mjs.
3. That reaches scripts (1 file).
4. It publishes to PyPI and @mcptoolshop/prompt-crafter (npm) to npm (on a run by hand, only with dry_run false).

## Who reads the results

release writes nothing this map can see.

## The other doors

**ci** runs verify.py.

**Deploy site to GitHub Pages** runs site/astro.config.mjs and site/src/, and deploys the site.

**pcraft** (a command people run) runs src/pcraft/cli/__init__.py and reaches scripts.

## What breaks what

- **scripts** is imported by 1 part (src), and by 1 more only from tests; it sits on the path of 2 doors.
- **src** is imported by 1 part (scripts), and by 1 more only from tests; it sits on the path of 2 doors.
- **the repository root** is imported only from tests, by 1 part (tests), and sits on the path of 2 doors.

## What tends to change together

- **src/pcraft/core/receipt/asset_record.py** and **tests/test_receipt_replay.py** changed together in 6 of 7 commits, and the tests part imports the src part.
- **tests/test_verify_legs.py** and **verify.py** changed together in 7 of 9 commits, and the tests part imports the repository root.
- **src/pcraft/core/gate/checkpoint.py** and **tests/test_feat_checkpoint.py** changed together in 5 of 7 commits, and the tests part imports the src part.
- **src/pcraft/core/contract/loader.py** and **tests/test_amend_contract.py** changed together in 8 of 12 commits, and the tests part imports the src part.
- **src/pcraft/core/gate/exit_contract.py** and **tests/test_gate_exit.py** changed together in 6 of 9 commits, and the tests part imports the src part.

1 file changed together with its own test, as expected.

Confidence is low: fewer than 20 source files reach 10 revisions in the window.

Window: 180 days; a pair counts from 3 shared commits, since 12 source files reach 10 revisions; the floor rises to 10 when 25 do.

## What no test touches

- **npm** is imported by no test.

## Written but never read

No place this map can see is written, so none goes unread.

## Helpers that look duplicated

No two parts export a helper that looks alike.

## Generated, never hand-edited

Nothing in this repository writes to a tracked place this map can see.

## Hand-authored

People write .github/, docs/, the repository root and site/; 12 writes with paths built at run time may land here.

## Where to start

.github/workflows/ci.yml → verify.py

Read those in order to follow one pull request end to end.

## What this map cannot see

- 8 import sites could not be resolved.
- 12 writes and 15 reads use paths built at run time and are not named here.
- 1 read goes to a temporary directory, not to this repository.
- 2 commands are built at run time and not followed.
- Statistics confidence is low: fewer than 20 source files reach 10 revisions in the window.

Regenerate with `npx --yes @dogfood-lab/atlas map`.
