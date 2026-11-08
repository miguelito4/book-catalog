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


# --- cleaning Reading List metadata -------------------------------------------------

SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor",
               "of", "on", "or", "over", "the", "to", "with", "via", "vs"}


DEGREES = {"phd", "ph.d.", "ph.d", "md", "m.d.", "dphil", "esq", "esq."}
GENERATIONAL = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def _flip(name: str) -> str:
    """'Last, First' -> 'First Last' (only when there's exactly one comma).
    'Name, Ph.D.' drops the degree; 'Name, Jr.' -> 'Name Jr.'."""
    if name.count(",") == 1:
        last, first = (p.strip() for p in name.split(","))
        if first.lower() in DEGREES:
            return last
        if first.lower() in GENERATIONAL:
            return f"{last} {first}"
        return f"{first} {last}".strip() if first else last
    return name


def clean_author(raw: str) -> str:
    """Reading List 'Authors' -> display names.

    Normal:  'Szalay, David'                          -> 'David Szalay'
    Mangled: 'Joyce, Appleby\\,'  (a credited 'Appleby, Joyce' split again
             and its comma escaped)                    -> 'Joyce Appleby'
    Noise:   '..., Kevin (Hubble science operations manager)' role dropped.
    Multiple authors are separated by ';'.
    """
    out = []
    for a in (raw or "").split(";"):
        a = a.strip()
        if not a:
            continue
        a = re.sub(r"(?<!\\),", "\x00", a, count=1)   # the one real separator
        if "\x00" in a:
            last, first = (p.strip() for p in a.split("\x00", 1))
            a = f"{first} {last}".strip()
        a = a.replace("\\,", ",")                   # unescape
        a = re.sub(r"\s*\([^)]*\)", "", a).strip(" ,")   # drop '(role)'
        a = _flip(a) if "," in a else a              # credited 'Last, First' inside
        out.append(re.sub(r"\s+", " ", a))
    return "; ".join(out)


def clean_title(title: str) -> str:
    """Strip a trailing 'A Novel', and title-case titles that arrive in sentence case."""
    t = re.sub(r"[\s:,-]+an? novel\s*$", "", (title or "").strip(), flags=re.I).strip()
    words = re.findall(r"[A-Za-z][\w'’-]*", t)
    significant = [w for w in words[1:] if w.lower() not in SMALL_WORDS]
    if significant and sum(w[0].islower() for w in significant) > len(significant) / 2:
        tokens = re.split(r"(\s+)", t)
        after_colon = True
        for i, tok in enumerate(tokens):
            if not tok.strip():
                continue
            core = tok.lower()
            if tok.isupper() and len(tok) > 1 or any(c.isupper() for c in tok[1:]):
                pass                                   # AI, McCarthy: leave alone
            elif after_colon or core.strip(":") not in SMALL_WORDS:
                tokens[i] = tok[0].upper() + tok[1:]
            after_colon = tok.endswith(":")
        t = "".join(tokens)
        t = t[0].upper() + t[1:]
    return t


# --- review form ---------------------------------------------------------------
#
# The PR description is the review form. Hidden HTML comments carry the keys so
# the visible labels can be human-friendly:
#
#   <!-- rl:ID -->                    starts a book section
#   Title: ...  /  Author: ...        editable; applied as written
#   - [ ] ⭐ Recommended <!-- f:recommended -->
#   - [x] Already in catalog (#412) <!-- f:link:412 -->
#   - [ ] Skip, don't add <!-- f:skip -->
#   - [x] Fiction <!-- t:fiction -->

BOOK_RE = re.compile(r"<!--\s*rl:(?P<id>[^\s>]+)\s*-->")
FIELD_RE = re.compile(r"^\s*(?P<k>Title|Author):\s*(?P<v>.*?)\s*$")
BOX_RE = re.compile(r"^\s*[-*]\s*\[(?P<x>[ xX])\]\s.*?<!--\s*(?P<key>[tf]):(?P<val>[^\s>]+)\s*-->")


def parse_review(markdown: str) -> dict[str, dict]:
    """Return {reading_list_id: {"themes", "recommended", "skip", "link", "title", "author"}}.
    title/author are None unless the section has a non-empty Title:/Author: line."""
    result: dict[str, dict] = {}
    current = None
    for line in markdown.splitlines():
        m = BOOK_RE.search(line)
        if m:
            current = {"themes": [], "recommended": False, "skip": False, "link": None,
                       "title": None, "author": None}
            result[m.group("id")] = current
            continue
        f = FIELD_RE.match(line)
        if f and current is not None:
            current[f.group("k").lower()] = f.group("v") or None
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


def render_review(pending: list[dict], vocab: list[dict], decisions: dict | None = None) -> str:
    """Render the review form. `decisions` (from parse_review of an open PR's body)
    carries over ticks already made, so a re-sync never discards review work."""
    decisions = decisions or {}
    n = len(pending)
    lines = [
        f"## Review: {n} book{'s' if n != 1 else ''} finished in Reading List",
        "",
        "Tick themes and ⭐ Recommended for each book, then **merge** to add them to the catalog. "
        "Fix a title or author by editing its `Title:` / `Author:` line. "
        "Suggested themes are pre-checked. Possible duplicates arrive with *Already in catalog* checked: "
        "leave it to link the existing entry, or untick it to add as a new book.",
        "",
        "_The checkboxes in this description are what gets applied. Edit them here, not in `pending.json`._",
        "",
    ]
    for p in pending:
        prior = decisions.get(p["reading_list_id"])
        title = (prior or {}).get("title") or p["title"]
        author = (prior or {}).get("author") or p.get("author") or ""
        meta = [f"finished {p['date_read']}"]
        if p.get("page_count"):
            meta.append(f"{p['page_count']} pp.")
        if p.get("year_published"):
            meta.append(f"pub. {p['year_published']}")
        lines += ["---", "", f"### {title}", f"<!-- rl:{p['reading_list_id']} -->",
                  f"Title: {title}  ", f"Author: {author}  ", " · ".join(meta), ""]
        if p.get("theme_source"):
            lines.append(f"<sub>Themes suggested by {p['theme_source']}"
                         + (f": {p['theme_reason']}" if p.get("theme_reason") else "") + "</sub>")
            lines.append("")
        dup = p.get("possible_duplicate")
        star = prior["recommended"] if prior else False
        link = (prior["link"] == dup["id"]) if (prior and dup) else bool(dup)
        skip = prior["skip"] if prior else False
        lines.append(f"- [{'x' if star else ' '}] ⭐ Recommended <!-- f:recommended -->")
        if dup:
            lines.append(f"- [{'x' if link else ' '}] Already in catalog: #{dup['id']} *{dup['title']}* "
                         f"({dup['reason']}) <!-- f:link:{dup['id']} -->")
        lines.append(f"- [{'x' if skip else ' '}] Skip, don't add <!-- f:skip -->")
        lines += ["", "**Themes**"]
        suggested = set(prior["themes"] if prior else (p.get("suggested_themes") or []))
        for t in vocab:
            box = "x" if t["slug"] in suggested else " "
            lines.append(f"- [{box}] {t['name']} <!-- t:{t['slug']} -->")
        lines.append("")
    return "\n".join(lines)
