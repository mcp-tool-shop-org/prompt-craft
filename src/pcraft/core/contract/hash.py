"""Canonical contract hash for provenance (PIN_PER_STEP).

The hash is computed over the RESOLVED contract (faction + character merged), so the same hash
implies the same atom list, the same must_not set, and the same identity refs -- i.e. the same gate.
It is stored in every asset receipt; a replay recomputes it and asserts equality."""

from __future__ import annotations

import hashlib
import json

from .schema import ResolvedContract


def _canonical(obj: object) -> object:
    """Recursively sort dict keys so serialization is order-independent."""
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_canonical(x) for x in obj]
    return obj


def contract_hash(resolved: ResolvedContract) -> str:
    """A stable sha256 over the canonical JSON of the resolved contract."""
    payload = _canonical(resolved.model_dump(mode="json"))
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
