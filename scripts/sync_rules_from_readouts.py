#!/usr/bin/env python3
"""Generate domains/image/rules/encoder_craft.md from the readouts sprites-knowledge DB.

The encoder rules are GENERATED, never hand-copied: the readouts ``prompt-craft`` lane is the single
source of truth (103 verified, source-cited recipes). This keeps the rule file drift-free and
PIN_PER_STEP-replayable — the file carries a generation header naming the DB, the lane, the row
count, and the DB currency date; everything below the header is reproducible from the same DB.

Lane selection (reused verbatim from the borrow audit):
    WHERE c.slug = 'prompt-craft'   (JOIN categories c ON c.id = r.category_id)
cross-checked against ``r.wave_id = (SELECT id FROM waves WHERE wave_number = 2)`` — both must return
103 rows; a divergence is an ANDON halt, not a silent partial render. arXiv ids are parsed from
``sources.url`` (``sources.identifier`` is NULL for this lane). Anti-pattern / 'avoid' rows are
rendered as explicit DON'T rules (their value is the negative space).

Windows note: run with PYTHONUTF8=1 (the lane text carries em-dashes / non-ASCII).

Usage:
    python scripts/sync_rules_from_readouts.py [--db PATH] [--out PATH] [--filter FTS_QUERY]
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

try:  # be robust on the Windows cp1252 console
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path("E:/AI/readouts/sprites-knowledge/recipes.db")
DEFAULT_OUT = REPO_ROOT / "src" / "pcraft" / "domains" / "image" / "rules" / "encoder_craft.md"
LANE_SLUG = "prompt-craft"
EXPECTED_ROWS = 103

ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", re.I)

# slug-prefix -> sub-section label, in render order
PREFIX_ORDER = ["clip", "t5", "llm", "depict", "struct", "face", "neg", "seed"]
PREFIX_LABELS = {
    "clip": "CLIP encoder (SDXL dual-encoder)",
    "t5": "T5 encoder",
    "llm": "LLM prompt expansion",
    "depict": "Depictability",
    "struct": "Structured / compositional prompting",
    "face": "Face / identity",
    "neg": "Negative prompting",
    "seed": "Seed & sampling",
}


def _fail(msg: str) -> None:
    print(f"error[SYNC]: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _lane_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    by_slug = con.execute(
        """SELECT r.id, r.slug, r.name, r.kind, r.engine_family, r.base_model_family,
                  r.claim, r.summary, r.design_implication, r.status, r.evidence_strength,
                  r.verified, r.verify_note
           FROM recipes r JOIN categories c ON c.id = r.category_id
           WHERE c.slug = ? ORDER BY r.slug""",
        (LANE_SLUG,),
    ).fetchall()
    # ANDON cross-check: the wave-2 selection must agree, row-for-row count.
    by_wave = con.execute(
        "SELECT COUNT(*) FROM recipes WHERE wave_id = (SELECT id FROM waves WHERE wave_number = 2)"
    ).fetchone()[0]
    if len(by_slug) != by_wave:
        _fail(f"lane divergence: slug='{LANE_SLUG}' -> {len(by_slug)} rows, wave 2 -> {by_wave} rows")
    if len(by_slug) != EXPECTED_ROWS:
        print(
            f"warning[SYNC]: expected {EXPECTED_ROWS} lane rows, got {len(by_slug)} "
            "(the lane may have grown — review before committing)",
            file=sys.stderr,
        )
    return by_slug


def _sources_by_recipe(con: sqlite3.Connection) -> dict[int, list[sqlite3.Row]]:
    rows = con.execute(
        """SELECT recipe_id, title, authors, year, url, claim
           FROM sources
           WHERE recipe_id IN (SELECT id FROM recipes
                               WHERE category_id = (SELECT id FROM categories WHERE slug = ?))
           ORDER BY recipe_id, id""",
        (LANE_SLUG,),
    ).fetchall()
    out: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        out.setdefault(row["recipe_id"], []).append(row)
    return out


def _meta_updated(con: sqlite3.Connection) -> str:
    try:
        for key in ("updated", "currency", "date", "latest_wave"):
            row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            if row:
                return row[0]
        return "unknown"
    except sqlite3.Error:
        return "unknown"


def _prefix(slug: str) -> str:
    return slug.split("-", 1)[0]


def _render_source(s: sqlite3.Row) -> str:
    title = (s["title"] or "source").strip()
    url = (s["url"] or "").strip()
    authors = (s["authors"] or "").strip()
    year = s["year"]
    link = f"[{title}]({url})" if url else title
    meta = ", ".join(p for p in (authors, str(year) if year else "") if p)
    arxiv = ARXIV_RE.search(url or "")
    tag = f" arXiv:{arxiv.group(1)}" if arxiv else ""
    claim = (s["claim"] or "").strip()
    tail = f" — {claim}" if claim else ""
    return f"{link}" + (f" ({meta})" if meta else "") + tail + tag


def _render_recipe(r: sqlite3.Row, sources: list[sqlite3.Row]) -> str:
    is_dont = (r["kind"] == "anti-pattern") or (r["status"] == "avoid")
    marker = "❌ DON'T — " if is_dont else ""
    head = f"### {marker}{r['name']} · `{r['status']}` · {r['evidence_strength']}"
    lines = [head, "", f"**{r['claim']}**", ""]
    if r["summary"]:
        lines += [r["summary"].strip(), ""]
    if r["design_implication"]:
        lines.append(f"- **For the pipeline:** {r['design_implication'].strip()}")
    meta_bits = [f"**Engine:** {r['engine_family'] or 'n/a'}", f"**Base:** {r['base_model_family'] or 'n/a'}", f"**Kind:** {r['kind'] or 'n/a'}"]
    lines.append("- " + " · ".join(meta_bits))
    if r["verify_note"]:
        lines.append(f"- **Verify:** {r['verify_note'].strip()}")
    if sources:
        rendered = " ; ".join(_render_source(s) for s in sources)
        lines.append(f"- **Sources:** {rendered}")
    lines.append("")
    return "\n".join(lines)


def generate(db_path: Path, out_path: Path) -> None:
    if not db_path.exists():
        _fail(f"readouts DB not found at {db_path} (set --db or READOUTS_DB). The committed "
              "encoder_craft.md stands until a machine with the DB regenerates it.")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = _lane_rows(con)
        sources = _sources_by_recipe(con)
        updated = _meta_updated(con)
    finally:
        con.close()

    by_prefix: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_prefix.setdefault(_prefix(r["slug"]), []).append(r)

    out = [
        "# Encoder craft & text-encoder rules (SDXL / CLIP / T5)",
        "",
        "<!-- GENERATED FILE — DO NOT HAND-EDIT. Regenerate with scripts/sync_rules_from_readouts.py -->",
        "",
        f"> Generated from the readouts **sprites-knowledge** DB, lane = category slug "
        f"`{LANE_SLUG}` (wave 2). Source: `{db_path.as_posix()}` · **{len(rows)} recipes** · "
        f"DB currency: `{updated}`.",
        ">",
        "> The DB is the single source of truth. Re-run the sync to refresh; never edit below this "
        "line. Debunked folklore is rendered as explicit ❌ DON'T rules — keep the negative space.",
        "",
    ]

    ordered_prefixes = [p for p in PREFIX_ORDER if p in by_prefix] + sorted(
        p for p in by_prefix if p not in PREFIX_ORDER
    )
    for prefix in ordered_prefixes:
        out.append(f"## {PREFIX_LABELS.get(prefix, prefix)}")
        out.append("")
        for r in by_prefix[prefix]:
            out.append(_render_recipe(r, sources.get(r["id"], [])))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({len(rows)} recipes across {len(ordered_prefixes)} sections)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=Path(__import__("os").environ.get("READOUTS_DB", DEFAULT_DB)))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--filter", default=None, help="(reserved) FTS query to regenerate a subset")
    args = ap.parse_args()
    generate(args.db, args.out)


if __name__ == "__main__":
    main()
