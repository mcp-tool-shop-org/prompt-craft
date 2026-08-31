"""3-zone, per-clause, calibrated thresholds (gate-verifier discipline).

No global magic constant. Each clause type (``siglip2`` / ``vqa`` / ``palette`` / a named sub-gate)
gets a band: ``PASS`` (>= high) / ``FAIL`` (<= low) / ``UNCERTAIN`` (between). Only the UNCERTAIN
band routes to a human checkpoint. Bands are **defaults**, stored versioned
(``sprite.calibration.json``, ``sprite.cal.v1``) and stamped into every receipt so a decision can be
replayed against the table that made it; recalibrate when the generator or verifier checkpoint
changes (both pinned).

TWO version-shaped strings live here and they are not the same kind of thing. ``version``
("sprite.cal.v1") is the CALIBRATION version -- data, a name for these numbers. ``$schema``
(``THRESHOLDS_SCHEMA_ID``) is the READER contract, the sibling of the contract file's
``prompt-craft/contract.v1`` and the receipt's ``schema_version``. Alongside them,
``fingerprint()`` is the content hash of the band VALUES: it is what makes an undeclared retune
detectable, since ``version`` is hand-maintained and nothing else binds it to the numbers it
names. The file is read by this build, its ``version`` is stamped into every receipt, and both
that version and this fingerprint are asserted on replay -- which is why the format belongs in
STABILITY.md's on-disk table alongside the other two, where it is not yet listed.

They are NOT calibrated against a human-labelled holdout. An earlier version of this docstring said
they were, and README.md retracts that claim by name as one it could not support -- so the sentence
survived in `src/` for the whole life of the correction. A docstring that outranks the front door on
a claim the front door has already withdrawn is the defect this package exists to catch."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ...errors import PromptCraftError
from ..contract.compile_questions import Polarity

THRESHOLDS_SCHEMA_ID = "prompt-craft/thresholds.v1"
"""The on-disk calibration format this build reads. NOT the calibration version.

F-3637b97f: this file is the third on-disk format the product reads and was the only one with no
forward-compatibility path. Its ``version`` field ('sprite.cal.v1') is the CALIBRATION version --
data, a statement about which numbers these are -- and it sits next to 'contract.v1' and
'schema_version: 1', which are READER contracts, meaning something entirely different. So a table
from a newer build was funnelled into the one hardcoded ValidationError sentence and reported as
'failed band invariants (high >= low, values in [0, 1])' on a table whose every band is valid,
with a hint telling the operator to recalibrate a table that is not miscalibrated.

The receipt reader next door had already been given exactly this treatment (see
``asset_record.RECORD_SCHEMA_VERSION``), and its docstring states the reasoning in general terms:
"no way to tell written-by-a-newer-prompt-craft from corrupt". Every word applied here.

Absent means v1, the same back-compat rule the receipt reader uses, so every calibration file on
disk -- the shipped one included -- keeps loading."""

_SUPPORTED_THRESHOLD_SCHEMAS = frozenset({THRESHOLDS_SCHEMA_ID})


class Zone(StrEnum):
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

    def describe(self, polarity: Polarity = Polarity.affirm) -> str:
        """The two numbers that graded a score, read in the direction the atom is asked (F-b1b29cef).

        Every score the operator reads is printed in ONE column whose meaning changes per row.
        The shipped sprite table is palette 0.85/0.50, vqa 0.80/0.40, siglip2 0.10/0.01 -- three
        scales, the outermost pair fifty times apart -- so ``[FAIL] palette 0.050`` can sit eight
        lines above ``[PASS] no_rival_colours 0.005``: ten times smaller and it passes. The band
        NAME was already on the line (F-00cfd3f8 put it there for attribution); the numbers are
        what make the name readable as calibration.

        Polarity is not decoration here. ``zone()`` INVERTS for a ``negate`` (must_not) probe --
        a HIGH "is it present?" score is a FAIL, because the forbidden thing is present -- so
        rendering the affirm reading on a negate row would be a confident WRONG statement about
        calibration, which is the class of defect the band key was added to remove rather than
        one to reintroduce a line lower.
        """
        if polarity is Polarity.affirm:
            return f"PASS >={self.high:.2f}, FAIL <={self.low:.2f}"
        return f"FAIL >={self.high:.2f}, PASS <={self.low:.2f}"


class ThresholdTable(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    schema_id: str = Field(default=THRESHOLDS_SCHEMA_ID, alias="$schema")
    version: str
    bands: dict[str, Band]
    default: Band
    notes: str = ""
    calibrated_on: str = ""

    def fingerprint(self) -> str:
        """A stable content hash of the band VALUES -- the thing ``version`` is supposed to describe.

        F-70ea9458: the only mechanism protecting against threshold drift was a hand-maintained
        string that nothing bound to the numbers. MEASURED: retuning vqa from {0.80, 0.40} to
        {0.20, 0.05} and siglip2 from {0.10, 0.01} to {0.90, 0.80} left both tables reporting
        ``version == 'sprite.cal.v1'``, a vqa score of 0.50 moved from UNCERTAIN to PASS, and
        ``replay`` compared two identical strings and reported success -- exactly the failure
        STABILITY.md's compensating guarantee names ("a decision made under one table cannot be
        silently replayed under another").

        This does NOT make a retune a breaking change; the promise that bands are data and will be
        retuned is unchanged. It makes an UNDECLARED retune detectable, which is the half the
        string comparison never delivered.

        Only ``bands`` and ``default`` are hashed. ``notes`` and ``calibrated_on`` are prose about
        the numbers -- the shipped table's own notes invite editing them ("Recalibrate when the
        generator or verifier checkpoint changes") -- and a reworded note is not a re-decision.
        ``version`` is excluded too: it is compared separately, and folding it in would make the
        fingerprint unable to answer "the label moved but the numbers did not".
        """
        payload = {
            "bands": {k: [self.bands[k].high, self.bands[k].low] for k in sorted(self.bands)},
            "default": [self.default.high, self.default.low],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

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
    except OSError as err:
        raise PromptCraftError(
            "IO_THRESHOLDS_READ", f"could not read thresholds {p}: {err.strerror or err}", cause=err
        ) from err
    except json.JSONDecodeError as err:
        # F-5592ffad, the IO_RECORD_READ shape applied to its sibling: "you pointed at nothing"
        # and "this file is damaged" arrived as one byte-identical sentence, so the message could
        # not distinguish the two even though the recovery differs.
        raise PromptCraftError(
            "IO_THRESHOLDS_READ", f"could not read thresholds {p}: not valid JSON ({err})", cause=err
        ) from err
    if not isinstance(data, dict):
        raise PromptCraftError(
            "CONFIG_THRESHOLDS_INVALID", f"threshold table {p} is valid JSON but not an object"
        )
    # Absent means v1: every calibration file written before the marker existed keeps loading,
    # which is the entire point of adding it. Present-and-unknown is a DIFFERENT answer from
    # invalid -- see THRESHOLDS_SCHEMA_ID.
    raw = data.get("$schema", data.get("schema_id"))
    schema_id = THRESHOLDS_SCHEMA_ID if raw is None else str(raw)
    if schema_id not in _SUPPORTED_THRESHOLD_SCHEMAS:
        raise PromptCraftError(
            "CONFIG_THRESHOLDS_SCHEMA_UNSUPPORTED",
            f"threshold table {p} declares $schema {schema_id!r}; this build reads "
            f"{sorted(_SUPPORTED_THRESHOLD_SCHEMAS)}",
        )
    return _READERS[schema_id](data, p)


def _read_v1(data: dict, p: Path) -> ThresholdTable:
    try:
        return ThresholdTable.model_validate(data)
    except ValidationError as err:
        raise PromptCraftError(
            "CONFIG_THRESHOLDS_INVALID", f"threshold table {p} {_describe(err)}", cause=err
        ) from err


_READERS = {THRESHOLDS_SCHEMA_ID: _read_v1}


_MAX_REPORTED_ERRORS = 4
"""How many field-level locations the default (non-debug) message names before it stops.
A diagnosis, not a dump: ``--debug`` still carries every one of them, via ``cause``."""


def _describe(err: ValidationError, what: str = "table") -> str:
    """Say what pydantic actually objected to.

    F-3637b97f: every ValidationError was collapsed into one literal -- "failed band invariants
    (high >= low, values in [0, 1])" -- so a missing ``default`` key, an unknown field name and a
    genuinely inverted band all reported the same sentence, and two of the three named an
    invariant that held. The message is derived from the error locations instead; the code is
    unchanged, because STABILITY.md says to parse the code and not the prose.

    CORRECTED IN PLACE (coordinator addition, F-eaa870d6 family). The aggregate was joined with
    ``"; "`` -- a delimiter that also occurs INSIDE a pydantic ``msg``, since a ``msg`` is free
    text produced by a validator this file does not own (``model_validator`` raises whatever
    sentence its author wrote). So a reader could not tell one entry ending in a semicolon from
    the boundary between two entries, and neither could a script splitting on it. This is the
    third instance of the same delimiter collision in the package; ``core.contract.loader`` is
    the sibling being fixed in the same wave, and the shape converged on is: an explicit
    ``[n]`` index per entry plus ``" | "`` between them, so the separator is a two-token sequence
    that carries a bracket, and every entry announces its own start.

    The convergence is by FORMAT, not by import: the sibling's shared helper lives under
    ``core.contract``, and reaching across from ``core.gate`` into a sibling subpackage for a
    string formatter would buy one function at the cost of a dependency edge between two
    subpackages that have no other reason to know about each other. If that helper is ever
    promoted to a shared location this function should call it.

    Only ``loc`` and ``msg`` are used. The offending ``input`` value is deliberately left out: it
    is arbitrary text from a file we did not write, and this string is printed to a console whose
    codepage we do not control -- the same rule ``loader._describe`` states.

    ``what`` names the thing being validated (F-6f6fc50e). It defaults to ``"table"``, so every
    message this function already produced is byte-for-byte unchanged; the labelled-holdout
    loader next door passes ``"holdout row"``. That IS an import rather than a third copy of the
    format, and the objection recorded above does not apply to it: ``holdout`` is in this same
    subpackage, so no dependency edge between two subpackages is created. The rule stands as
    written -- reach across a subpackage boundary for a string formatter, no; share one inside
    a subpackage, yes.
    """
    entries = err.errors()
    shown = entries[:_MAX_REPORTED_ERRORS]
    parts = [
        f"[{i}] {'.'.join(str(x) for x in entry.get('loc', ())) or f'<{what}>'}: "
        f"{entry.get('msg', 'is invalid')}"
        for i, entry in enumerate(shown, 1)
    ]
    if not parts:
        return f"is not a valid {what}"
    summary = " | ".join(parts)
    remaining = len(entries) - len(shown)
    if remaining > 0:
        summary += f" | (+{remaining} more, see --debug)"
    return f"is not a valid {what} -- {len(entries)} error(s): {summary}"
