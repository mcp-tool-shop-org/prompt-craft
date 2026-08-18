"""Reference lock — pose + identity as one conditioned generate.

Measured 2026-08-18 on the shipped ashen-reaver plates (Imagine
multi-ref ``image_edit``, not SDXL ControlNet):

- Identity plate + OpenPose map → both hands on the axe, face and
  hashed triple-bar held. The stick-figure map was enough for a
  reference-conditioned model to move the grip.
- Identity plate + costume plate → identity held, pose did not move.

So the lock is joint refs, not two bolted-on SDXL adapters. SDXL
ControlNet + IP-Adapter stay the local/diffusers path. ``method=reference``
on an identity plate means "these files are joint refs for a
reference-conditioned model (Cloud / Imagine / Kontext)." SDXL does
not pretend to run that model.
"""

from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, ConfigDict

from . import conditioning as cond


class ReferenceLock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pose: list[str]
    identity: list[str]
    costume: list[str]
    extras: list[str] = []

    def all_paths(self) -> list[str]:
        return [*self.pose, *self.identity, *self.costume, *self.extras]


def assemble(conditioning: dict) -> ReferenceLock:
    """Resolve every named plate into a lock pack. Missing refs still refuse."""
    bound = cond.bind_refs(conditioning)
    pose = list(bound.get("pose_refs") or [])
    identity: list[str] = []
    costume: list[str] = []
    extras: list[str] = []
    for raw in bound.get("identity_refs") or []:
        if not isinstance(raw, dict) or not raw.get("plate"):
            continue
        plate = str(raw["plate"])
        scope = str(raw.get("scope") or "face")
        if scope in {"face", "full", "silhouette"}:
            identity.append(plate)
        elif scope == "costume":
            costume.append(plate)
        else:
            extras.append(plate)
    return ReferenceLock(pose=pose, identity=identity, costume=costume, extras=extras)


def as_generate_refs(lock: ReferenceLock) -> list[Path]:
    """Order a reference-conditioned editor wants: identity, then pose, then costume."""
    return [Path(p) for p in (*lock.identity, *lock.pose, *lock.costume, *lock.extras)]
