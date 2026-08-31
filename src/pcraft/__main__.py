"""``python -m pcraft`` -- same surface as the ``pcraft`` console script."""

from .cli import app

# prog_name pinned: click otherwise derives it from argv[0], so the npm launcher (which
# spawns `python -m pcraft.cli`) showed `Usage: python -m pcraft.cli ...` to a user who
# typed `pcraft` and may not have that invocation on PATH at all (Phase 9, F7). Every door
# into this CLI reports the one name every door answers to.
app(prog_name="pcraft")
