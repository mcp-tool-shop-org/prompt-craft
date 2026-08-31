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
reference-conditioned model (Cloud / Imagine / Kontext)." ``pcraft
recipe`` emits that graph (stitch + left crop + fist-only Fill).
SDXL does not pretend to run that model.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ....errors import PromptCraftError
from . import conditioning as cond


class ReferenceLock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pose: list[str]
    identity: list[str]
    costume: list[str]
    extras: list[str] = []
    # plate path -> the method the contract DECLARED for it. The Kontext recipe applies every bound
    # plate as a reference stitch regardless; recording the declared method is what lets the receipt
    # name the instrument instead of implying one.
    methods: dict[str, str] = Field(default_factory=dict)

    def all_paths(self) -> list[str]:
        return [*self.pose, *self.identity, *self.costume, *self.extras]

    def method_for(self, plate: str) -> str:
        return self.methods.get(plate, "")


def assemble(conditioning: dict) -> ReferenceLock:
    """Resolve every named plate into a lock pack. Missing refs still refuse.

    F-43da2300: this used to bucket every ref that carried a plate by ``scope`` ALONE, ignoring
    ``method`` entirely. Two measured consequences, both fixed here:

    1. ``method=none`` -- documented in ``conditioning`` as a skip -- was promoted into
       ``lock.identity`` and became THE Kontext stitch identity of the emitted Cloud graph, and it
       SHADOWED the real ``method=reference`` plate purely by list order (``as_generate_refs`` takes
       ``refs[0]``). A skipped plate is not an identity lock: skip methods are dropped now.
    2. Because ``bind_refs`` deliberately does not resolve a skip-method plate, that plate also
       escaped ``GATE_CONDITIONING_REF_MISSING`` -- so a path that did not exist on disk could reach
       the graph as a ``LoadImage`` filename. Dropping it closes that door too.

    An unrecognised method is refused by name rather than bucketed (the F-916e73b6 allow-list, at
    the lock layer): a receipt must never stamp a plate no generator applied.
    """
    bound = cond.bind_refs(conditioning)
    unsupported = cond.unsupported_identity_methods(bound)
    if unsupported:
        raise PromptCraftError(
            "GATE_CONDITIONING_UNSUPPORTED",
            f"reference lock cannot bucket identity method(s) {unsupported}: "
            "no encoder is wired for that method",
            hint="Set identity_ref.method to ip_adapter, lora, instantid, reference, or none.",
        )
    pose = list(bound.get("pose_refs") or [])
    identity: list[str] = []
    costume: list[str] = []
    extras: list[str] = []
    methods: dict[str, str] = {}
    for raw in bound.get("identity_refs") or []:
        if not isinstance(raw, dict) or not raw.get("plate"):
            continue
        method = str(raw.get("method") or cond._IP_ADAPTER)
        if method in cond._SKIP_METHODS:
            continue  # method=none is a documented skip, never a lock
        plate = str(raw["plate"])
        scope = str(raw.get("scope") or "face")
        methods[plate] = method
        if scope in {"face", "full", "silhouette"}:
            identity.append(plate)
        elif scope == "costume":
            costume.append(plate)
        else:
            extras.append(plate)
    return ReferenceLock(
        pose=pose, identity=identity, costume=costume, extras=extras, methods=methods
    )


def as_generate_refs(lock: ReferenceLock) -> list[Path]:
    """Order a reference-conditioned editor wants: identity, then pose, then costume."""
    return [Path(p) for p in (*lock.identity, *lock.pose, *lock.costume, *lock.extras)]
