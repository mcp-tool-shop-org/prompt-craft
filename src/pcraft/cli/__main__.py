"""``python -m pcraft.cli`` -- same surface as the ``pcraft`` console script."""

from . import app

# prog_name pinned for the same reason as pcraft/__main__.py: this module is the exact
# invocation the npm launcher spawns, so without it every launcher user saw
# `Usage: python -m pcraft.cli ...` for a command they know as `pcraft` (Phase 9, F7).
app(prog_name="pcraft")
