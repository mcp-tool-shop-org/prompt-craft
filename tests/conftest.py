from __future__ import annotations

import pytest

from pcraft.sample import load_sprite_example


@pytest.fixture
def sprite_example():
    """(store, resolved_contract, thresholds, compiled_artifact) for the generic example."""
    return load_sprite_example()
