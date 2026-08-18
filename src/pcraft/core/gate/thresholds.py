"""3-zone, per-clause, calibrated thresholds (gate-verifier discipline).

No global magic constant. Each clause type (``siglip2`` / ``vqa`` / ``palette`` / a named sub-gate)
gets a band: ``PASS`` (>= high) / ``FAIL`` (<= low) / ``UNCERTAIN`` (between). Only the UNCERTAIN
band routes to a human checkpoint. Bands are calibrated against a human-labelled holdout and stored
versioned; recalibrate when the generator or verifier checkpoint changes (both pinned)."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ...errors import PromptCraftError
from ..contract.compile_questions import Polarity


class Zone(str, Enum):
    PASS = "PASS"
    UNCERTAIN = "UNCERTAIN"
    FAIL = "FAIL"
    NA = "NA"  # a parent failed; this atom was not evaluated
    SKIPPED = "SKIPPED"  # verifier unavailable (e.g. SigLIP2 not installed) — never silently a pass
    UNAVAILABLE = "UNAVAILABLE"  # roll-up only: no required atom produced a score


class Band(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high: float = Field(ge=0.0, le=1.0)  # score >= high  -> PASS
    low: float = Field(ge=0.0, le=1.0)  # score <= low   -> FAIL

    @model_validator(mode="after")
    def high_at_least_low(self) -> Band:
        if self.high < self.low:
            raise ValueError(f"band high ({self.high}) must be >= low ({self.low})")
        return self


class ThresholdTable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    bands: dict[str, Band]
    default: Band
    notes: str = ""
    calibrated_on: str = ""

    def band_for(self, key: str) -> Band:
        return self.bands.get(key, self.default)

    def zone(self, key: str, score: float, polarity: Polarity = Polarity.affirm) -> Zone:
        """Map a raw score to a zone. For a ``negate`` (must_not) probe the verdict inverts:
        a HIGH 'is it present?' score is a FAIL (the forbidden thing is present)."""
        band = self.band_for(key)
        if polarity is Polarity.affirm:
            if score >= band.high:
                return Zone.PASS
            if score <= band.low:
                return Zone.FAIL
            return Zone.UNCERTAIN
        # negate: present => bad
        if score >= band.high:
            return Zone.FAIL
        if score <= band.low:
            return Zone.PASS
        return Zone.UNCERTAIN


def load_thresholds(path: str | Path) -> ThresholdTable:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise PromptCraftError("IO_THRESHOLDS_READ", f"could not read thresholds {p}", cause=err) from err
    try:
        return ThresholdTable.model_validate(data)
    except ValidationError as err:
        raise PromptCraftError(
            "CONFIG_THRESHOLDS_INVALID",
            f"threshold table {p} failed band invariants (high >= low, values in [0, 1])",
            cause=err,
        ) from err
