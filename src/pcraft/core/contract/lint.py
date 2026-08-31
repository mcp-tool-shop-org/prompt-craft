"""SOFT authoring-quality advisories -- the pass ``pcraft validate`` never had (F-ae0e76f8).

``validate`` and ``ResolvedContract``'s own model validators enforce HARD structural
invariants -- schema shape, relaxation, duplicate ids, ``depends_on`` referential integrity
and acyclicity -- all fail-closed, all correct. Nothing checked the soft signals that do not
break loading but predict a bad gate run, and ``validate`` reports the compiled DAG as a bare
``questions: N`` count with no advisory pass at all.

THE HARD RULE OF THIS MODULE: it never refuses. ``lint_contract`` returns a list -- possibly
empty -- and raises nothing. It does not construct a ``PromptCraftError``, it has no exit
code, and ``validate`` / ``bind`` / ``gate`` keep their pass/fail semantics exactly as they
were. These are warnings a caller may print or ignore, never a new gate.

That is also why an advisory ``code`` carries its own ``LINT_`` namespace: an error code in
this package is a promise about an EXIT CODE (see ``pcraft.errors``' namespace table), and
these map to none. ``LINT_CODES`` is pinned in the test suite as disjoint from
``DEFAULT_HINTS`` so the two vocabularies cannot merge by accident.

The four rules, in the fixed order they are emitted:

1. ``LINT_MISSING_SPATIAL`` -- an atom with no ``spatial`` where a SIBLING of the same
   ``check_type`` has one. The finding measured this on the shipped example:
   ``example.character``'s two ``must_not`` atoms carry no ``spatial`` while its ``must_have``
   siblings (weapon: pose, face: region) prove the field is meaningful in that contract.
2. ``LINT_PALETTE_ENUM_NOT_HEX`` -- a ``check_type=palette`` atom whose ``enum`` names no
   ``#hex`` value. This is the health pass's own CLOSED F-00cfd3f8 caught at authoring time:
   a palette atom naming a colour by word falls through to a differently-calibrated verifier
   band, and nothing flagged it.
3. ``LINT_COLOUR_CLAIM_NOT_PALETTE`` -- a claim that names a colour on an atom that is not a
   palette check. The converse of rule 2.
4. ``LINT_MUST_NOT_ALL_OPTIONAL`` -- every negation in the contract is ``optional``, i.e. the
   whole ``must_not`` list runs, reports, and blocks nothing. Per ``MustNot.severity``'s own
   note, "promotion is the intended direction"; this says when nothing has been promoted yet.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from .schema import CheckType, ResolvedContract, Severity

LINT_MISSING_SPATIAL = "LINT_MISSING_SPATIAL"
LINT_PALETTE_ENUM_NOT_HEX = "LINT_PALETTE_ENUM_NOT_HEX"
LINT_COLOUR_CLAIM_NOT_PALETTE = "LINT_COLOUR_CLAIM_NOT_PALETTE"
LINT_MUST_NOT_ALL_OPTIONAL = "LINT_MUST_NOT_ALL_OPTIONAL"

LINT_CODES: tuple[str, ...] = (
    LINT_MISSING_SPATIAL,
    LINT_PALETTE_ENUM_NOT_HEX,
    LINT_COLOUR_CLAIM_NOT_PALETTE,
    LINT_MUST_NOT_ALL_OPTIONAL,
)
"""Every advisory this module can emit, in emission order. Advisory codes, NOT error codes."""

_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")

_COLOUR_WORDS: tuple[str, ...] = (
    "amber", "azure", "beige", "black", "blue", "bronze", "brown", "copper", "crimson",
    "cyan", "gold", "golden", "green", "grey", "gray", "indigo", "ivory", "magenta",
    "maroon", "navy", "olive", "orange", "pink", "purple", "red", "scarlet", "silver",
    "teal", "violet", "white", "yellow",
)
"""Deliberately conservative. Only unambiguous colour NAMES: a word that also names an object
("rose", "sand", "jade", "tan") would fire on claims that are about the object, and an
advisory nobody trusts is one nobody reads. Matched on a word boundary, so the compound
vocabulary the shipped contracts actually use -- "blood-red", "bone-white", "royal-blue" --
is found, since a hyphen is not a word character."""

_COLOUR = re.compile(r"\b(?:" + "|".join(_COLOUR_WORDS) + r")\b", re.IGNORECASE)


class LintAdvisory(BaseModel):
    """One non-blocking observation. Shaped like a refusal (code / message / hint) because it
    is read the same way -- but it is NOT an exception and carries no exit code."""

    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    hint: str
    atom_id: str | None = None  # absent for a contract-level advisory


def _all_items(resolved: ResolvedContract):
    """Every atom in one namespace, must_have first -- the order ``compile_questions`` uses."""
    return [("must_have", a) for a in resolved.must_have] + [
        ("must_not", m) for m in resolved.must_not
    ]


def _missing_spatial(resolved: ResolvedContract) -> list[LintAdvisory]:
    items = _all_items(resolved)
    with_spatial = {item.check_type for _polarity, item in items if item.spatial is not None}
    return [
        LintAdvisory(
            code=LINT_MISSING_SPATIAL,
            atom_id=item.id,
            message=(
                f"{polarity} atom {item.id!r} declares no spatial, but another "
                f"{item.check_type.value} atom in this contract does"
            ),
            hint=(
                "A sibling of the same check_type localizes its claim to a region or locks it "
                "with a pose, so the verifier tier is being told where to look for that one "
                "and not for this one. Add a spatial, or leave it out deliberately -- this is "
                "an observation, not a requirement."
            ),
        )
        for polarity, item in items
        if item.spatial is None and item.check_type in with_spatial
    ]


def _palette_enum_not_hex(resolved: ResolvedContract) -> list[LintAdvisory]:
    return [
        LintAdvisory(
            code=LINT_PALETTE_ENUM_NOT_HEX,
            atom_id=item.id,
            message=(
                f"{polarity} atom {item.id!r} is a palette check whose enum names no #hex value"
            ),
            hint=(
                "The palette tier compares pixels against colour VALUES. An enum of colour "
                "words is scored by a differently-calibrated band than the one this atom "
                "asks for. List the hex codes, e.g. #3a3a3a."
            ),
        )
        for polarity, item in _all_items(resolved)
        if item.check_type is CheckType.palette
        and not any(_HEX.search(entry) for entry in (item.enum or []))
    ]


def _colour_claim_not_palette(resolved: ResolvedContract) -> list[LintAdvisory]:
    return [
        LintAdvisory(
            code=LINT_COLOUR_CLAIM_NOT_PALETTE,
            atom_id=item.id,
            message=(
                f"{polarity} atom {item.id!r} names a colour in its claim but is checked as "
                f"{item.check_type.value}, not palette"
            ),
            hint=(
                "A colour stated in prose is verified by a language-grounded tier, which is "
                "not what measures colour. If the colour is the claim, a palette atom with "
                "hex values checks it deterministically; if it is incidental, ignore this."
            ),
        )
        for polarity, item in _all_items(resolved)
        if item.check_type is not CheckType.palette and _COLOUR.search(item.claim)
    ]


def _must_not_all_optional(resolved: ResolvedContract) -> list[LintAdvisory]:
    if not resolved.must_not:
        return []
    if any(m.severity is Severity.required for m in resolved.must_not):
        return []
    return [
        LintAdvisory(
            code=LINT_MUST_NOT_ALL_OPTIONAL,
            message=(
                f"all {len(resolved.must_not)} must_not atom(s) are optional, so no negation "
                f"in {resolved.id!r} can block a bind"
            ),
            hint=(
                "Optional negations still run, still score and still ride the transcript -- "
                "they simply stop nothing. MustNot.severity's intended direction is "
                "promotion: measure the verifier on absence, then raise the severity with "
                "the measurement in hand."
            ),
        )
    ]


def lint_contract(resolved: ResolvedContract) -> list[LintAdvisory]:
    """Advisory-only authoring signals. NEVER raises; never affects an exit code.

    Deterministic: rules run in ``LINT_CODES`` order, and within a rule the atoms are visited
    in resolved declaration order (must_have, then must_not) -- so two runs over one contract
    produce the identical list, which is what makes the output diffable in CI.
    """
    return [
        *_missing_spatial(resolved),
        *_palette_enum_not_hex(resolved),
        *_colour_claim_not_palette(resolved),
        *_must_not_all_optional(resolved),
    ]
