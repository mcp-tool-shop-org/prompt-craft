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


class SpriteSubdomain:
    name = "sprite"
    directions = EIGHT_DIRECTIONS
    contracts_dir = CONTRACTS_DIR
    thresholds_path = THRESHOLDS_PATH

    def identity_subgate(self, **kwargs) -> IdentitySubGate:
        return IdentitySubGate(**kwargs)
