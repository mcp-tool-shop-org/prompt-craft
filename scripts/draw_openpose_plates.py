"""Draw ControlNet-shaped OpenPose maps. Stdlib only. No GPU, no Pillow.

BODY_25 layout + the CMU limb palette so an OpenPose ControlNet sees a
real pose lock, not a picture of a skeleton. The two-hand plate matches
the ashen-reaver weapon atom (both wrists on a shaft in front of the chest).
The turnaround set is the same figure yawed in 45-degree steps, foot-anchored.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 512

# BODY_25 names in index order
NOSE, NECK = 0, 1
R_SHO, R_ELB, R_WRI = 2, 3, 4
L_SHO, L_ELB, L_WRI = 5, 6, 7
MID_HIP = 8
R_HIP, R_KNE, R_ANK = 9, 10, 11
L_HIP, L_KNE, L_ANK = 12, 13, 14
R_EYE, L_EYE, R_EAR, L_EAR = 15, 16, 17, 18
L_BIG, L_SML, L_HEEL = 19, 20, 21
R_BIG, R_SML, R_HEEL = 22, 23, 24

# CMU-ish limb colors (RGB) — saturated, on black
LIMBS = [
    ((NECK, MID_HIP), (0, 0, 255)),
    ((NECK, R_SHO), (0, 85, 255)),
    ((NECK, L_SHO), (0, 170, 255)),
    ((R_SHO, R_ELB), (0, 255, 170)),
    ((R_ELB, R_WRI), (0, 255, 85)),
    ((L_SHO, L_ELB), (85, 255, 0)),
    ((L_ELB, L_WRI), (170, 255, 0)),
    ((MID_HIP, R_HIP), (255, 170, 0)),
    ((R_HIP, R_KNE), (255, 85, 0)),
    ((R_KNE, R_ANK), (255, 0, 0)),
    ((MID_HIP, L_HIP), (255, 0, 85)),
    ((L_HIP, L_KNE), (255, 0, 170)),
    ((L_KNE, L_ANK), (255, 0, 255)),
    ((NECK, NOSE), (85, 0, 255)),
    ((NOSE, R_EYE), (170, 0, 255)),
    ((R_EYE, R_EAR), (255, 0, 255)),
    ((NOSE, L_EYE), (255, 0, 170)),
    ((L_EYE, L_EAR), (255, 0, 85)),
    ((L_ANK, L_BIG), (170, 255, 255)),
    ((L_BIG, L_SML), (85, 255, 255)),
    ((L_ANK, L_HEEL), (0, 255, 255)),
    ((R_ANK, R_BIG), (255, 255, 170)),
    ((R_BIG, R_SML), (255, 255, 85)),
    ((R_ANK, R_HEEL), (255, 255, 0)),
]

JOINT_RGB = (255, 255, 255)

# Two-hand axe grip: wrists together in front of the chest.
# Coordinates are metres-ish: y up, x right, z toward camera (front).
_FRONT = {
    NOSE: (0.00, 1.66, 0.06),
    NECK: (0.00, 1.50, 0.00),
    R_SHO: (-0.28, 1.48, 0.00),
    R_ELB: (-0.14, 1.26, 0.16),
    R_WRI: (-0.04, 1.12, 0.22),
    L_SHO: (0.28, 1.48, 0.00),
    L_ELB: (0.14, 1.26, 0.16),
    L_WRI: (0.04, 1.12, 0.22),
    MID_HIP: (0.00, 1.00, 0.00),
    R_HIP: (-0.11, 0.98, 0.00),
    R_KNE: (-0.12, 0.52, 0.03),
    R_ANK: (-0.12, 0.08, 0.00),
    L_HIP: (0.11, 0.98, 0.00),
    L_KNE: (0.12, 0.52, 0.03),
    L_ANK: (0.12, 0.08, 0.00),
    R_EYE: (-0.04, 1.69, 0.07),
    L_EYE: (0.04, 1.69, 0.07),
    R_EAR: (-0.08, 1.66, 0.00),
    L_EAR: (0.08, 1.66, 0.00),
    L_BIG: (0.13, 0.02, 0.06),
    L_SML: (0.10, 0.02, 0.05),
    L_HEEL: (0.12, 0.04, -0.04),
    R_BIG: (-0.13, 0.02, 0.06),
    R_SML: (-0.10, 0.02, 0.05),
    R_HEEL: (-0.12, 0.04, -0.04),
}

YAWS = {
    "front": 0.0,
    "front-right": 45.0,
    "right": 90.0,
    "back-right": 135.0,
    "back": 180.0,
    "back-left": 225.0,
    "left": 270.0,
    "front-left": 315.0,
}

SPRITE = Path(__file__).resolve().parents[1] / "src" / "pcraft" / "domains" / "image" / "subdomains" / "sprite"


def _project(x: float, y: float, z: float, yaw_deg: float) -> tuple[int, int]:
    yaw = math.radians(yaw_deg)
    xr = x * math.cos(yaw) + z * math.sin(yaw)
    px = int(SIZE * (0.50 + xr * 0.40))
    py = int(SIZE * (0.92 - y * 0.50))  # feet near the bottom (foot-anchored)
    return px, py


def _put(px: bytearray, x: int, y: int, rgb: tuple[int, int, int]) -> None:
    if 0 <= x < SIZE and 0 <= y < SIZE:
        i = (y * SIZE + x) * 3
        px[i : i + 3] = bytes(rgb)


def _line(px: bytearray, x0: int, y0: int, x1: int, y1: int, rgb: tuple[int, int, int], width: int = 4) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        for ox in range(-width // 2, width // 2 + 1):
            for oy in range(-width // 2, width // 2 + 1):
                _put(px, x + ox, y + oy, rgb)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def _dot(px: bytearray, cx: int, cy: int, rgb: tuple[int, int, int], radius: int = 5) -> None:
    r2 = radius * radius
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                _put(px, x, y, rgb)


def _write_png(path: Path, rgb: bytes) -> None:
    raw = b"".join(b"\x00" + rgb[y * SIZE * 3 : (y + 1) * SIZE * 3] for y in range(SIZE))

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def render(yaw_deg: float) -> bytes:
    px = bytearray(SIZE * SIZE * 3)  # black
    pts = {i: _project(*xyz, yaw_deg) for i, xyz in _FRONT.items()}
    for (a, b), color in LIMBS:
        _line(px, *pts[a], *pts[b], color)
    for i in pts:
        _dot(px, *pts[i], JOINT_RGB)
    return bytes(px)


def main() -> None:
    two_hand = SPRITE / "poses" / "two-hand-weapon.openpose.png"
    _write_png(two_hand, render(0.0))
    print(f"wrote {two_hand}")
    for name, yaw in YAWS.items():
        path = SPRITE / "poses" / "turnaround" / f"{name}.openpose.png"
        _write_png(path, render(yaw))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
