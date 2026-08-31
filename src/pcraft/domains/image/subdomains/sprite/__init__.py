"""The sprite subdomain: the reference fill every later domain copies.

Adds, on top of the image plugin: the 8-direction turnaround, a pose ControlNet ref per direction
(foot-anchored so the sprite is engine-placeable), the contracts/ + thresholds/ data, and the
cross-view CLIP-I identity sub-gate."""

from __future__ import annotations

from pathlib import Path

from .identity_subgate import IdentitySubGate

HERE = Path(__file__).parent

EIGHT_DIRECTIONS = [
    "front",
    "front-right",
    "right",
    "back-right",
    "back",
    "back-left",
    "left",
    "front-left",
]

# pose ControlNet reference per direction (foot-anchored, bottom-centre, engine-placeable scale)
POSE_REFS = {d: f"poses/turnaround/{d}.openpose.png" for d in EIGHT_DIRECTIONS}

FOOT_ANCHOR = "lanczos downsample to 64px, foot-anchored bottom-centre"

CONTRACTS_DIR = HERE / "contracts"
THRESHOLDS_PATH = HERE / "thresholds" / "sprite.calibration.json"
EXAMPLE_CHARACTER_ID = "char:ashen-reaver"
EXAMPLE_FACTION_ID = "faction:ashen-pact"

# F-85852fb7: the method=reference TWIN of the pair above -- the SDXL example's two plates both
# declare method=ip_adapter, so `pcraft recipe` (the Cloud Kontext stitch + left crop + fist-only
# Fill) correctly refuses it and the entire recipe surface shipped with no runnable packaged demo.
#
# It is a PAIR because a character-only twin does not work. ``loader._merge_identity_refs`` places
# the inherited faction plate FIRST in the merged identity_refs, and ``reference_lock.assemble``
# calls ``refuse_unmeasured_identity_family`` over the WHOLE merged list -- so an inherited
# ip_adapter costume plate refuses the run before the character's own reference plate is reached.
# Overriding the inherited plate's method is refused as CONTRACT_RELAXATION, so the twin is a
# separate id pair rather than a subclass of the shipped faction. Both refusals are correct
# (F-0e41e735 / F-43da2300) and neither is relaxed to make this example run.
CLOUD_EXAMPLE_CHARACTER_ID = "char:ashen-reaver-cloud"
CLOUD_EXAMPLE_FACTION_ID = "faction:ashen-pact-cloud"


class SpriteSubdomain:
    name = "sprite"
    directions = EIGHT_DIRECTIONS
    contracts_dir = CONTRACTS_DIR
    thresholds_path = THRESHOLDS_PATH

    def identity_subgate(self, **kwargs) -> IdentitySubGate:
        return IdentitySubGate(**kwargs)
