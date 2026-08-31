# Releasing prompt-craft

This file owns the release **sequence** -- what happens in which order, and why the order
is load-bearing. The mechanics of the release workflow itself (its triggers, its guards,
what a dry run does and deliberately does not prove) are documented in
`.github/workflows/release.yml`'s header, beside the YAML they describe; that header is
the authority on the workflow's shape, this file is the authority on the sequence, and
neither restates the other's half.

Publishing is irreversible. A version number, once taken on PyPI or npm, is taken forever.
Everything below exists so the irreversible step is the last one and the cheapest one to
have gotten right.

### The gate, and where it lives

- `python verify.py` (checkout) / `python verify.py --installed` (after
  `pip install -e ".[dev]"`) runs every hard gate: lint, typecheck, the suite, the suite
  under `-O`, the wheel and sdist build, and a smoke of the built wheel installed into a
  throwaway venv. It does NOT run the dependency audit -- `--audit` adds that, and it is
  off by default so the gate stays a function of the tree rather than of today's advisory
  feed.
- `.github/workflows/ci.yml` runs the same command on 3.11 and 3.13, then `pip-audit`.
- `.github/workflows/release.yml` runs it again on the tagged tree, then publishes by OIDC.
  Its header comment is the authority on that workflow's shape; read it before editing it.

### Prove the release workflow BEFORE cutting the tag

The release workflow is the one nobody exercises, which makes it the one that discovers a
problem during a release. It has two rungs, and both publish nothing.

**0. Check nothing is already armed.**

```
gh run list --workflow=release.yml --limit 10
```

Any run in `waiting` is holding an environment approval against some tag. Resolve it
(approve or reject) before cutting another. This is not hypothetical: the run triggered by
the v1.0.0 release sat in `waiting` for 302 hours, armed against that tag and holding a dist
artifact built from a workflow revision no longer on `main`, until it was cancelled by hand.
v1.0.0 was tagged and never published; both registries were at 0.4.0 at that point.

**1. Rung one -- gates only. No approval, no deployment, nothing left armed.**

```
gh workflow run release.yml --ref v1.0.1 -f dry_run=true
```

`dry_run` defaults to `true`, so the accidental dispatch is the harmless one. Green means
checkout/setup/install ran on the Node24 action majors, `verify.py --installed` passed on
that tag's tree, `twine check` passed, and tag == pyproject == npm/package.json. The `pypi`
and `npm` jobs are skipped, so the `release` environment is never entered: no deployment is
created and no reviewer is asked. The run posts a step summary saying exactly that.

**2. Rung two -- prove the environment gate, still publishing nothing.**

```
gh workflow run release.yml --ref v1.0.1 -f dry_run=false
```

This arms the environment on purpose. Both publish jobs pause for the required reviewer
BEFORE either registry is touched, so the safe move is to REJECT both pending deployments at
the prompt. Rejected-not-published proves the reviewer rule is real. If the jobs run straight
through without pausing, the environment's protection rules are gone and the publisher pin is
a label again -- stop and fix that before releasing.

Neither rung can prove a publish SUCCEEDS. Only a publish does that. What they prove is that
nothing between the tag and the registry is broken, which is the part that can be checked for
free.

### The release sequence

1. Bump `pyproject.toml` `[project].version` and `npm/package.json` `version` together. The
   release workflow refuses if they disagree, and refuses again if the tag disagrees with
   either.
2. Update `CHANGELOG.md` and any status/version claims in `README.md`.
3. Run the translations (they must land in the SAME commit as the README change: a GitHub
   release tag is immutable, so translations that arrive in a follow-up commit are stale at
   that tag forever).
4. `python verify.py --installed` locally. Green.
5. One commit with all of the above. Push. Confirm CI is green on it.
6. Cut the tag from that commit and run rung one, then rung two, against it.
7. Publish the GitHub release. The `release: published` event drives release.yml, which runs
   the whole gate again on the tagged tree and then pauses at the environment for approval.
8. Approve. Watch both jobs. `npm` asks the registry first and reports honestly if the
   version is already there, so a re-run is safe.

### If something goes wrong

See `COMPENSATORS.md` for the named undo of each irreversible action. Two that have no undo
and so have prevention instead:

- A tag that disagrees with the tree. Do NOT force-push or move the tag -- a GitHub Release
  may already point at it, and moving it silently changes what that release refers to. Cut a
  new tag from a commit where the manifests already read the right version.
- A version published to one registry and not the other. Fix forward with a patch release;
  neither registry lets a number be reused.
