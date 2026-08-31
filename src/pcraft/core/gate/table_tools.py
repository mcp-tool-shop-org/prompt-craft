"""Authoring-time tooling for a calibration table: lint, fingerprint, diff.

F-1d76b4ba. Retuning is a hand-edit of JSON with nothing standing between the operator and a
table that is loaded at GATE time. Three questions nothing answered:

(1) DOES THIS TABLE DECLARE THE BANDS THE GATE WILL LOOK UP. A band key the table does not
declare falls silently to ``default``. MEASURED: a table declaring ``vqua`` instead of ``vqa``
returns ``band_for('vqa') -> default``, and a 0.55 vqa score that would be UNCERTAIN under the
real 0.80/0.40 band grades PASS under the shipped 0.70/0.40 default -- no error, no warning, and
nothing in the transcript saying the default was used, because ``AtomVerdict.band_key`` records
the KEY that was looked up and not that the lookup missed. ``lint`` turns that silent regrade
into a finding at authoring time.

(2) WHAT IS THIS CANDIDATE'S FINGERPRINT. The values-hash on ``ThresholdTable`` is what every
receipt is compared against on replay, and no command printed it -- so an operator meeting a
VALUE-drift refusal that quotes a content hash had no way to ask a candidate table for its own.
``describe`` is that read.

(3) DID THE VALUES MOVE WITHOUT THE VERSION MOVING. Two version-shaped strings live in the
table and mean different things: ``$schema`` is the READER contract, ``version`` is the
CALIBRATION label. ``diff`` states the one combination that matters -- "values changed, version
did NOT" -- which is the exact undeclared retune the fingerprint exists to catch.

WHERE THE FENCE IS. Band VALUES are data, not interface (STABILITY.md), and they will be
retuned. So this module may refuse a table the gate cannot USE, and may never refuse a number
the author meant: ``lint`` reads keys and never reads values. It runs when asked, not at load
time -- ``load_thresholds`` is untouched, and so is ``band_for``'s fall to ``default``, which is
a RUNTIME path with its own compatibility story. And a refusal here takes its OWN code
(``CONFIG_THRESHOLDS_UNUSABLE``): per the F-09f30018 ruling, one covered machine-parseable code
carrying two unrelated meanings is exactly what "parse the code, not the prose" forbids.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from ...errors import PromptCraftError
from ..contract.schema import CheckType
from .thresholds import Band, ThresholdTable


def needed_band_keys() -> frozenset[str]:
    """The band keys a gate run WILL look up, derived from the ``CheckType`` enum.

    Exact rather than approximate: ``harness.evaluate`` zones every atom through
    ``_band_key(q.check_type, ...)``, whose fallback is the atom's declared ``check_type`` -- a
    closed enum. Derived rather than listed so a ``CheckType`` added tomorrow widens this by
    itself; a hardcoded copy would leave the new check_type falling to ``default`` with nothing
    saying so, which is the defect this function exists to catch.
    """
    return frozenset(ct.value for ct in CheckType)


def reachable_band_keys(verifier_ids: Iterable[str] = ()) -> frozenset[str]:
    """Every key something could key on: the needed set, plus the verifier families in play.

    ``_band_key`` redirects a score to the band named by the leading segment of the deciding
    verifier's id (``siglip2.screen.v1`` -> ``siglip2``), but ONLY when the table already
    declares that band -- so a verifier family can never be "needed and missing", it can only
    make an otherwise-dead declaration live. That asymmetry is why families appear here and not
    in ``needed_band_keys``.
    """
    return needed_band_keys() | {vid.split("@", 1)[0].split(".", 1)[0] for vid in verifier_ids}


def lint(
    table: ThresholdTable,
    needed_keys: Iterable[str] | None = None,
    *,
    verifier_ids: Iterable[str] = (),
) -> list[str]:
    """Structural problems with ``table``, in reading order. Empty means clean.

    Two findings, and they are two halves of one typo:

      * a needed key the table does not declare -- every atom of that check_type will grade
        against ``default`` and nothing will say so;
      * a declared key nothing can key on -- dead configuration, and the other end of the
        missing key above. Reporting BOTH is what makes ``vqua``/``vqa`` unmistakable instead of
        two unrelated-looking complaints.

    Never a finding: any band VALUE. High, low, how far they moved, whether they look sensible
    -- all data, all the author's call, all outside what this may have an opinion about.

    ``needed_keys`` defaults to ``needed_band_keys()``. Pass a narrower set for a table that
    deliberately serves only some check_types and means ``default`` for the rest.
    """
    needed = set(needed_band_keys() if needed_keys is None else needed_keys)
    reachable = set(reachable_band_keys(verifier_ids)) | needed
    declared = set(table.bands)

    missing = sorted(needed - declared)
    dead = sorted(declared - reachable)
    problems: list[str] = []
    for key in missing:
        near = difflib.get_close_matches(key, dead, n=1, cutoff=0.6)
        did_you_mean = f" (this table declares {near[0]!r} -- did you mean {key!r}?)" if near else ""
        problems.append(
            f"band {key!r} is not declared, so every {key!r} atom grades against `default` "
            f"({table.default.high} / {table.default.low}) and nothing in the transcript says "
            f"so{did_you_mean}"
        )
    for key in dead:
        near = difflib.get_close_matches(key, missing, n=1, cutoff=0.6)
        did_you_mean = f" -- did you mean {near[0]!r}?" if near else ""
        problems.append(
            f"band {key!r} is declared but nothing can key on it: it is not a check_type "
            f"({', '.join(sorted(needed))}) and not a verifier family in play{did_you_mean}"
        )
    return problems


def check(
    table: ThresholdTable,
    needed_keys: Iterable[str] | None = None,
    *,
    verifier_ids: Iterable[str] = (),
    source: str = "",
) -> None:
    """Raise ``CONFIG_THRESHOLDS_UNUSABLE`` if ``lint`` has anything to say. Otherwise silent.

    Deliberately NOT called by ``load_thresholds``. A table that misses a band still loads and
    still grades -- that is the shipped runtime behaviour and it has its own compatibility
    story. This is the authoring-time door, taken when an author asks for it.
    """
    problems = lint(table, needed_keys, verifier_ids=verifier_ids)
    if not problems:
        return
    where = f" {source}" if source else ""
    numbered = " | ".join(f"[{i}] {p}" for i, p in enumerate(problems, 1))
    raise PromptCraftError(
        "CONFIG_THRESHOLDS_UNUSABLE",
        f"threshold table{where} parses, but the gate will not find the bands in it -- "
        f"{len(problems)} problem(s): {numbered}",
    )


class BandRetune(BaseModel):
    """One band whose numbers moved. ``key`` is present on both sides by construction."""

    model_config = ConfigDict(extra="forbid")
    key: str
    was: Band
    now: Band


class TableDiff(BaseModel):
    """What moved between two tables, and whether the label moved with it.

    ``added`` / ``removed`` / ``retuned`` / ``default_retuned`` are the EXPLANATION of a
    fingerprint difference, never a second opinion about whether there is one: ``values_changed``
    reads the values-hash, which is the same field every receipt is compared against on replay.
    """

    model_config = ConfigDict(extra="forbid")
    was_version: str
    now_version: str
    was_fingerprint: str
    now_fingerprint: str
    added: list[str]
    removed: list[str]
    retuned: list[BandRetune]
    default_retuned: bool

    @property
    def version_changed(self) -> bool:
        return self.was_version != self.now_version

    @property
    def values_changed(self) -> bool:
        return self.was_fingerprint != self.now_fingerprint

    @property
    def undeclared_retune(self) -> bool:
        """The numbers moved and the label did not -- a decision replayed under a table that is
        not the one it names. Not a breaking change; a change that cannot be seen."""
        return self.values_changed and not self.version_changed

    def summary(self) -> str:
        """One ASCII line. The surface that prints it owns the wrapping."""
        if not self.values_changed and not self.version_changed:
            return f"identical: version {self.was_version!r}, values {self.was_fingerprint}"
        parts: list[str] = []
        if self.added:
            parts.append(f"added {', '.join(self.added)}")
        if self.removed:
            parts.append(f"removed {', '.join(self.removed)}")
        if self.retuned:
            parts.append(f"retuned {', '.join(r.key for r in self.retuned)}")
        if self.default_retuned:
            parts.append("retuned default")
        detail = "; ".join(parts) or "no band changed"
        if self.undeclared_retune:
            head = (
                f"values changed, version did NOT (still {self.was_version!r}): "
                f"{self.was_fingerprint} -> {self.now_fingerprint}. An undeclared retune -- "
                f"bump the version, or restore the values"
            )
        elif self.values_changed:
            head = (
                f"values changed and version moved {self.was_version!r} -> {self.now_version!r}: "
                f"{self.was_fingerprint} -> {self.now_fingerprint}"
            )
        else:
            head = (
                f"version moved {self.was_version!r} -> {self.now_version!r}, values did not "
                f"(still {self.was_fingerprint})"
            )
        return f"{head}. {detail}."


def diff(was: ThresholdTable, now: ThresholdTable) -> TableDiff:
    """Compare two tables. Only ``bands``, ``default`` and ``version`` are read.

    ``notes`` and ``calibrated_on`` are prose about the numbers -- the shipped table's own notes
    invite editing them -- and a reworded note is not a re-decision, which is precisely why the
    fingerprint excludes them too.
    """
    was_bands, now_bands = was.bands, now.bands
    return TableDiff(
        was_version=was.version,
        now_version=now.version,
        was_fingerprint=was.fingerprint(),
        now_fingerprint=now.fingerprint(),
        added=sorted(set(now_bands) - set(was_bands)),
        removed=sorted(set(was_bands) - set(now_bands)),
        retuned=[
            BandRetune(key=k, was=was_bands[k], now=now_bands[k])
            for k in sorted(set(was_bands) & set(now_bands))
            if (was_bands[k].high, was_bands[k].low) != (now_bands[k].high, now_bands[k].low)
        ],
        default_retuned=(was.default.high, was.default.low)
        != (now.default.high, now.default.low),
    )


def describe(table: ThresholdTable) -> str:
    """A table's identity in one ASCII block: both version-shaped strings, and the values-hash.

    All three are printed together on purpose. ``$schema`` is the READER contract, ``version``
    is the CALIBRATION label, and the fingerprint is the only one of the three that is BOUND to
    the numbers -- a reader who sees one without the others cannot tell which question they are
    holding the answer to. The fingerprint line is the string a VALUE-drift refusal quotes, so
    it is printed in the form that refusal prints it.
    """
    lines = [
        f"version:     {table.version}",
        f"$schema:     {table.schema_id}",
        f"fingerprint: {table.fingerprint()}",
        f"default:     {table.default.describe()}",
    ]
    lines.extend(
        f"band {key}:{' ' * max(1, 7 - len(key))}{table.bands[key].describe()}"
        for key in sorted(table.bands)
    )
    if table.calibrated_on:
        lines.append(f"calibrated on: {table.calibrated_on}")
    return "\n".join(lines)


__all__ = [
    "BandRetune",
    "TableDiff",
    "check",
    "describe",
    "diff",
    "lint",
    "needed_band_keys",
    "reachable_band_keys",
]
