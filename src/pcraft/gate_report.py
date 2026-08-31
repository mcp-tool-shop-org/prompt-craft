"""Human-readable rendering of a gate transcript (for the CLI and demo output).

PARTIAL / FAIL / UNAVAILABLE must not read as a wall of green PASSes with
one asterisk (To Trust or to Think, arXiv:2102.09692). Unconfirmed and
failed atoms print first. The tier census is its own line, not a log.

Width and indentation follow the one convention in ``pcraft.errors`` (see the block above
``LINE_WIDTH`` there): the verdict row is the headline and owns column 0's structure, and
everything secondary hangs on a labelled continuation line under the atom id.
"""

from __future__ import annotations

from .core.contract.compile_questions import QuestionDAG
from .core.gate.harness import AtomVerdict, GateTranscript, TierCensus
from .core.gate.thresholds import Zone
from .errors import LINE_WIDTH, tier_list, wrap_field

_ZONE_W = 9
"""CORRECTED IN PLACE (F-00cc16d9). This was 11, padded for ``UNAVAILABLE`` -- which
``harness._rollup``'s own docstring calls roll-up-only and which no atom-scoring path
produces, so two columns of every row were dead. 9 fits every zone an atom can actually
reach (UNCERTAIN is the longest at 9); a directly-constructed UNAVAILABLE verdict still
renders, two columns wider than its neighbours."""

_ATOM_W = 18

_INDENT = 2 + 1 + _ZONE_W + 1 + 1
"""The column the atom id starts in, and therefore the column every continuation hangs at."""

_LABEL_W = 8
"""``why:`` / ``saw:`` / ``claim:`` padded to one width, so the labels form a column."""


def format_transcript(t: GateTranscript, *, dag: QuestionDAG | None = None) -> str:
    """Render a transcript for a human.

    ``dag`` is optional and additive (F-56203d3d). Without it this prints atom IDS only, so
    ``palette`` and ``no_rival_colours`` appear without the claims they are asserting -- while
    ``build_checkpoint`` one file over does print them, and ``pcraft gate`` compiles the DAG
    before calling this and then drops it. With it, each PROBLEM atom carries the question that
    was actually asked; passing rows do not, because a wall of claims under every green row is
    the "wall of green PASSes with one asterisk" this module's own docstring refuses.

    Keyword-only on purpose: the two shipped call sites pass one positional argument, and a
    keyword makes it impossible for a later caller to bind the wrong object into this slot.
    """
    census = t.tier_census
    lines = [
        f"gate overall: {t.overall.value}  (contract {t.contract_id})",
        f"thresholds: {t.thresholds_version or 'unversioned'}",
        _census_line(census),
    ]
    problem = [
        v for v in t.verdicts
        if v.zone in (Zone.FAIL, Zone.UNCERTAIN, Zone.SKIPPED, Zone.NA, Zone.UNAVAILABLE)
    ]
    rest = [v for v in t.verdicts if v not in problem]
    # CORRECTED IN PLACE (F-0c1a929a). The condition was ``problem and t.overall is not
    # Zone.PASS``, so on an overall-PASS run the whole grouping and every claim line
    # disappeared -- including for atoms whose own row read [FAIL] -- and the function fell to
    # the undifferentiated ``else`` branch, which never calls ``_why``. F-834dd470's sibling
    # regression closed the UNAVAILABLE half of this same condition and left the
    # ``overall is not Zone.PASS`` half standing.
    #
    # MEASURED on the shipped example with every atom at 0.95 and no_rival_colours at 0.005:
    # overall=PASS, and the three optional must_not atoms invert to FAIL under negate polarity.
    # The transcript printed 'gate overall: PASS' on line 1 and then ten rows in flat DAG order
    # -- seven [PASS] followed by three [FAIL] -- with no header, no reordering and no claims.
    # So the one run shape where a reader is most likely to stop after the first line was the
    # shape that hid its failures deepest. Reachable by default, not constructed: the shipped
    # faction and character contracts declare all five must_not atoms `optional` on purpose.
    #
    # ``problem`` being non-empty is the whole test. The header name is unchanged because it
    # stays true -- an atom that failed did fail, whatever the roll-up decided.
    if problem:
        lines.append("unconfirmed / failed:")
        for v in problem:
            lines.append(_fmt(v))
            lines.extend(_why(v, dag))
        if rest:
            lines.append("other atoms:")
            lines.extend(_fmt(v) for v in rest)
    else:
        lines.extend(_fmt(v) for v in t.verdicts)
    return "\n".join(lines)


def _census_line(census: TierCensus) -> str:
    """``tiers executed: 1 of 2  (required T0 T1; missing T0)``.

    CORRECTED IN PLACE (F-6acc1597). This read ``(executed [0, 1]; required [0, 1])`` -- raw
    Python list repr, three lines above rows already writing ``T0``/``T1``, and executed
    before required while ``checkpoint._census_line`` printed the same two lists in the
    opposite order. It also stated its own fact twice: ``2 of 2`` is ``len()`` of the two
    lists printed beside it. What the count does NOT imply is which tier is missing, so that
    is what the parenthesis says now, and only when something is.
    """
    missing = [tier for tier in census.required if tier not in census.executed]
    detail = f"required {tier_list(census.required)}"
    if missing:
        detail += f"; missing {tier_list(missing)}"
    return f"tiers executed: {census.n} of {census.m}  ({detail})"


def _why(v: AtomVerdict, dag: QuestionDAG | None) -> list[str]:
    """The reason, what the instrument saw, and the claim -- one labelled line each.

    CORRECTED IN PLACE (F-00cc16d9). All three used to ride the verdict row: ``reason`` and
    ``detail`` appended inline (``detail`` LAST, so it began past column 125 and was in the
    wrapped tail on every terminal), and ``_claim`` indented to column 24 -- a column that
    aligned with nothing, being 8 past the atom id and 11 short of the score. They are the
    WHY, they are what a reader stops on, and they now hang at ONE indent under the atom.

    Only PROBLEM atoms get these, for the same reason only problem atoms got a claim: a wall
    of bands and reasons under every green row is the wall of green this module refuses.
    """
    out: list[str] = []
    if v.reason:
        out += wrap_field("why:", v.reason, indent=_INDENT, label_width=_LABEL_W)
    # ``detail`` is what the instrument SAW -- which colours of the palette it hit, where the
    # localizer looked -- and it is rendered for the same reason the band numbers are
    # (F-b1b29cef): the score says which side of the line, and nothing else says why. Absent
    # for any verifier that does not publish one, which is the normal case, and an absent
    # detail adds no line at all.
    if v.detail:
        out += wrap_field("saw:", v.detail, indent=_INDENT, label_width=_LABEL_W)
    if dag is not None:
        question = dag.by_id(v.atom_id)
        if question is not None and question.text:
            out += wrap_field("claim:", question.text, indent=_INDENT, label_width=_LABEL_W)
    return out


def _fmt(v: AtomVerdict) -> str:
    """One verdict row: zone, atom, tier, score, polarity/severity -- and nothing else.

    MEASURED before the narrowing: 30 of 30 rows across the all-pass, one-FAIL and
    multi-UNCERTAIN shapes exceeded 80 columns and 120 (min 121, max 178 with a detail). The
    row's own columns were carefully aligned and the wrap destroyed that alignment in every
    shipped rendering, resuming at column 0 -- where every section header of this artifact
    lives. Nothing that can grow without bound rides this line any more.
    """
    score = f"{v.score:.3f}" if v.score is not None else "  -  "
    tier = f"T{v.tier_used}" if v.tier_used is not None else "--"
    return (
        f"  [{v.zone.value:{_ZONE_W}}] {v.atom_id:{_ATOM_W}} {tier:2}  {score}  "
        f"{v.polarity.value}/{v.severity.value}"
    )


__all__ = ["LINE_WIDTH", "format_transcript"]
