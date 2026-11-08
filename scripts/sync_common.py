#!/usr/bin/env python3
"""
Shared pieces for the Reading List sync (sync_reading_list.py / apply_pending.py).

- ensure_schema(): idempotent migration adding the sync bookkeeping
- theme vocabulary, title/author normalization, review-form rendering and parsing
"""

import re
import sqlite3
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "books.db"
INBOX = ROOT / "inbox"
PENDING_PATH = INBOX / "pending.json"
REVIEW_PATH = INBOX / "review.md"

# First sync picks up everything finished on or after this date (the last
# manual addition). Stored in the meta table so it's visible in books.sql.
DEFAULT_CUTOFF = "2026-08-04"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Add sync bookkeeping to an existing catalog. Safe to run repeatedly."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(books)")}
    if "reading_list_id" not in cols:
        conn.execute("ALTER TABLE books ADD COLUMN reading_list_id TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_books_reading_list_id "
        "ON books(reading_list_id) WHERE reading_list_id IS NOT NULL"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sync_skips (
               reading_list_id TEXT PRIMARY KEY,
               title TEXT,
               skipped_at TEXT DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('sync_cutoff', ?)", (DEFAULT_CUTOFF,)
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def themes(conn: sqlite3.Connection) -> list[dict]:
    """Theme vocabulary in display order, with counts and descriptions."""
    rows = conn.execute(
        """SELECT t.slug, t.name, t.description, COUNT(bt.book_id) AS n
           FROM themes t LEFT JOIN book_themes bt ON bt.theme_id = t.id
           GROUP BY t.id
           ORDER BY COALESCE(t.display_order, 999), t.name"""
    ).fetchall()
    return [dict(r) for r in rows]


# --- normalization for duplicate detection -----------------------------------

def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def norm_title(title: str) -> str:
    t = _fold(title).split(":")[0]                  # drop subtitle
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"^(the|a|an) ", "", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def author_surname(author: str) -> str:
    """'First Last' or 'Last, First' (first author only) -> 'last'."""
    a = _fold((author or "").split(";")[0].split(" and ")[0]).strip()
    if "," in a:
        a = a.split(",")[0]
    else:
        a = a.split()[-1] if a.split() else ""
    return re.sub(r"[^a-z]", "", a)


def norm_isbn(isbn: str) -> str:
    return re.sub(r"[^0-9Xx]", "", isbn or "").upper()


# --- review form ---------------------------------------------------------------
#
# The PR description is the review form. Hidden HTML comments carry the keys so
# the visible labels can be human-friendly:
#
#   <!-- rl:ID -->                    starts a book section
#   - [ ] ⭐ Recommended <!-- f:recommended -->
#   - [x] Already in catalog (#412) <!-- f:link:412 -->
#   - [ ] Skip, don't add <!-- f:skip -->
#   - [x] Fiction <!-- t:fiction -->

BOOK_RE = re.compile(r"<!--\s*rl:(?P<id>[^\s>]+)\s*-->")
BOX_RE = re.compile(r"^\s*[-*]\s*\[(?P<x>[ xX])\]\s.*?<!--\s*(?P<key>[tf]):(?P<val>[^\s>]+)\s*-->")


def parse_review(markdown: str) -> dict[str, dict]:
    """Return {reading_list_id: {"themes": [...], "recommended": bool, "skip": bool, "link": id|None}}."""
    result: dict[str, dict] = {}
    current = None
    for line in markdown.splitlines():
        m = BOOK_RE.search(line)
        if m:
            current = {"themes": [], "recommended": False, "skip": False, "link": None}
            result[m.group("id")] = current
            continue
        m = BOX_RE.match(line)
        if not (m and current is not None):
            continue
        checked = m.group("x").lower() == "x"
        key, val = m.group("key"), m.group("val")
        if key == "t" and checked:
            current["themes"].append(val)
        elif key == "f" and val == "recommended":
            current["recommended"] = checked
        elif key == "f" and val == "skip":
            current["skip"] = checked
        elif key == "f" and val.startswith("link:") and checked:
            current["link"] = int(val.split(":", 1)[1])
    return result


def render_review(pending: list[dict], vocab: list[dict]) -> str:
    n = len(pending)
    lines = [
        f"## Review: {n} book{'s' if n != 1 else ''} finished in Reading List",
        "",
        "Tick themes and ⭐ Recommended for each book, then **merge** to add them to the catalog. "
        "Suggested themes are pre-checked. Possible duplicates arrive with *Already in catalog* checked: "
        "leave it to link the existing entry, or untick it to add as a new book.",
        "",
        "_The checkboxes in this description are what gets applied. Edit them here, not in `pending.json`._",
        "",
    ]
    for p in pending:
        meta = [p.get("author") or "Unknown author", f"finished {p['date_read']}"]
        if p.get("page_count"):
            meta.append(f"{p['page_count']} pp.")
        lines += ["---", "", f"### {p['title']}", f"{' · '.join(meta)}", f"<!-- rl:{p['reading_list_id']} -->", ""]
        if p.get("theme_source"):
            lines.append(f"<sub>Themes suggested by {p['theme_source']}"
                         + (f": {p['theme_reason']}" if p.get("theme_reason") else "") + "</sub>")
            lines.append("")
        lines.append("- [ ] ⭐ Recommended <!-- f:recommended -->")
        dup = p.get("possible_duplicate")
        if dup:
            lines.append(f"- [x] Already in catalog: #{dup['id']} *{dup['title']}* ({dup['reason']}) "
                         f"<!-- f:link:{dup['id']} -->")
        lines.append("- [ ] Skip, don't add <!-- f:skip -->")
        lines += ["", "**Themes**"]
        suggested = set(p.get("suggested_themes") or [])
        for t in vocab:
            box = "x" if t["slug"] in suggested else " "
            lines.append(f"- [{box}] {t['name']} <!-- t:{t['slug']} -->")
        lines.append("")
    return "\n".join(lines)
