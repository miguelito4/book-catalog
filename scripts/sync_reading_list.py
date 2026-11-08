#!/usr/bin/env python3
"""
Turn a Reading List CSV export into a review batch.

Selects books finished on/after the sync cutoff that aren't already in the
catalog (by reading_list_id) or previously skipped, flags likely duplicates of
existing entries, enriches metadata (Open Library / Google Books), and suggests
themes (Claude, falling back to keyword matching). Writes:

    inbox/pending.json   enriched records, consumed by apply_pending.py
    inbox/review.md      the review form, used as the PR description

Nothing is written to the database.

Usage:
    python scripts/sync_reading_list.py                       # newest inbox/*.csv
    python scripts/sync_reading_list.py --csv export.csv
    python scripts/sync_reading_list.py --no-enrich --no-claude   # offline dry run

Env:
    ANTHROPIC_API_KEY   enables Claude theme suggestions
    CLAUDE_MODEL        default: claude-haiku-5-5
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sync_common import (  # noqa: E402
    INBOX, PENDING_PATH, REVIEW_PATH, author_surname, connect, ensure_schema,
    clean_author, clean_title, get_meta, norm_isbn, norm_title, parse_review,
    render_review, themes,
)
from preprocess_reading_list import guess_themes  # noqa: E402

CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
BATCH = 25


# --- selection -------------------------------------------------------------------

def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def candidates(rows, conn) -> list[dict]:
    cutoff = get_meta(conn, "sync_cutoff")
    known = {r[0] for r in conn.execute(
        "SELECT reading_list_id FROM books WHERE reading_list_id IS NOT NULL")}
    known |= {r[0] for r in conn.execute("SELECT reading_list_id FROM sync_skips")}

    out = []
    for r in rows:
        finished = (r.get("Finished Reading") or "").strip()[:10]
        rl_id = (r.get("Reading List ID") or "").strip()
        if not (finished and rl_id) or finished < cutoff:
            continue
        if (r.get("Did Not Finish") or "").strip():
            continue
        if rl_id in known:
            continue
        pub = (r.get("Publication Date") or "").strip()
        out.append({
            "reading_list_id": rl_id,
            "title": clean_title(r.get("Title") or ""),
            "subtitle": (r.get("Subtitle") or "").strip() or None,
            "author": clean_author(r.get("Authors") or "") or None,
            "isbn13": norm_isbn(r.get("ISBN-13")) or None,
            "page_count": to_int(r.get("Page Count")),
            "year_published": to_int(pub[:4]) if re.match(r"^\d{4}", pub) else None,
            "publisher": (r.get("Publisher") or "").strip() or None,
            "language": (r.get("Language Code") or "").strip() or None,
            "summary": (r.get("Description") or "").strip() or None,
            "date_started": (r.get("Started Reading") or "").strip()[:10] or None,
            "date_read": finished,
            "_subjects": r.get("Subjects") or "",
        })
    out.sort(key=lambda b: b["date_read"])
    return out


def find_duplicate(book: dict, conn):
    """Possible existing entry for this book, or None. Flagged for review, never auto-resolved."""
    if book.get("isbn13"):
        row = conn.execute(
            "SELECT id, title FROM books WHERE isbn13 = ? OR isbn = ?",
            (book["isbn13"], book["isbn13"]),
        ).fetchone()
        if row:
            return {"id": row["id"], "title": row["title"], "reason": "same ISBN-13"}
    t, a = norm_title(book["title"]), author_surname(book.get("author") or "")
    if not t:
        return None
    for row in conn.execute("SELECT id, title, author FROM books"):
        if norm_title(row["title"]) == t and (not a or author_surname(row["author"] or "") == a):
            return {"id": row["id"], "title": row["title"], "reason": "same title and author"}
    return None


# --- enrichment ----------------------------------------------------------------

def enrich(book: dict) -> None:
    """Fill gaps (cover, summary, pages, publisher, OL key) in place, without touching the DB."""
    from models import Book
    from enrich import enrich_book

    fields = ["title", "subtitle", "author", "isbn13", "page_count", "publisher", "summary"]
    b = Book(**{k: book.get(k) for k in fields})
    try:
        enrich_book(b, save=False)
    except Exception as e:  # network trouble shouldn't sink the batch
        print(f"  enrichment failed: {e}")
        return
    for k in ["cover_url", "summary", "page_count", "publisher", "openlibrary_key"]:
        if getattr(b, k, None) and not book.get(k):
            book[k] = getattr(b, k)


# --- theme suggestions -----------------------------------------------------------

def theme_examples(conn, per_theme=6) -> dict[str, list[str]]:
    ex = {}
    for t in themes(conn):
        rows = conn.execute(
            """SELECT b.title, b.author FROM books b
               JOIN book_themes bt ON bt.book_id = b.id
               JOIN themes t ON t.id = bt.theme_id
               WHERE t.slug = ? ORDER BY b.id DESC LIMIT ?""",
            (t["slug"], per_theme),
        ).fetchall()
        ex[t["slug"]] = [f"{r['title']} ({r['author']})" for r in rows]
    return ex


def suggest_with_claude(books, vocab, examples) -> dict:
    import requests

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {}
    theme_lines = "\n".join(
        f"- {t['slug']}: {t['name']}"
        + (f" ({t['description']})" if t.get("description") else "")
        + f". {t['n']} books, e.g. " + "; ".join(examples.get(t["slug"], [])[:6])
        for t in vocab
    )
    out = {}
    for i in range(0, len(books), BATCH):
        chunk = books[i:i + BATCH]
        listing = "\n".join(
            json.dumps({
                "id": b["reading_list_id"], "title": b["title"], "author": b.get("author"),
                "subjects": b.get("_subjects", "")[:200],
                "summary": (b.get("summary") or "")[:500],
            }, ensure_ascii=False)
            for b in chunk
        )
        prompt = f"""You assign themes to books in a personal reading catalog. Use ONLY these theme slugs:

{theme_lines}

Most books in this catalog have exactly one theme (average 1.2). Give two only when a book genuinely belongs to both (e.g. a political biography). Match how the existing examples are classified, not generic genre labels.

Books (one JSON object per line):
{listing}

Respond with only a JSON object mapping each id to {{"themes": [slugs], "reason": "<=12 words"}}."""
        try:
            resp = requests.post(
                CLAUDE_URL,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": CLAUDE_MODEL, "max_tokens": 4000,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=90,
            )
            resp.raise_for_status()
            text = "".join(c.get("text", "") for c in resp.json().get("content", []))
            data = json.loads(text[text.index("{"): text.rindex("}") + 1])
            out.update(data)
        except Exception as e:
            print(f"Claude theme suggestion failed for batch {i // BATCH + 1}: {e}", file=sys.stderr)
    return out


def assign_themes(books, conn, use_claude: bool) -> None:
    vocab = themes(conn)
    valid = {t["slug"] for t in vocab}
    claude = suggest_with_claude(books, vocab, theme_examples(conn)) if use_claude else {}
    for b in books:
        s = claude.get(b["reading_list_id"]) or {}
        picked = [t for t in (s.get("themes") or []) if t in valid]
        if picked:
            b["suggested_themes"], b["theme_source"] = picked, "Claude"
            b["theme_reason"] = (s.get("reason") or "").strip()
        else:
            b["suggested_themes"] = [t for t in guess_themes(b.get("_subjects", "")) if t in valid]
            b["theme_source"] = "subject keywords" if b["suggested_themes"] else None


# --- main ---------------------------------------------------------------------------

def newest_csv() -> Path | None:
    files = sorted(INBOX.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a review batch from a Reading List export")
    ap.add_argument("--csv", type=Path, help="Reading List export (default: newest inbox/*.csv)")
    ap.add_argument("--no-enrich", action="store_true", help="Skip Open Library / Google Books lookups")
    ap.add_argument("--no-claude", action="store_true", help="Keyword theme matching only")
    ap.add_argument("--preserve-from", type=Path,
                    help="Existing review form (open PR body) whose ticks should carry over")
    ap.add_argument("--limit", type=int, default=40,
                    help="Max books per batch (keeps the PR description under GitHub's size limit)")
    args = ap.parse_args()

    path = args.csv or newest_csv()
    if not path or not path.exists():
        print("No Reading List CSV found (pass --csv or put one in inbox/).", file=sys.stderr)
        return 1

    conn = connect()
    ensure_schema(conn)
    books = candidates(read_csv(path), conn)
    print(f"{path.name}: {len(books)} new finished book(s) since {get_meta(conn, 'sync_cutoff')}")

    if len(books) > args.limit:
        print(f"Batching: first {args.limit} now, the rest after this batch is merged")
        books = books[:args.limit]

    if not books:
        for p in (PENDING_PATH, REVIEW_PATH):
            p.unlink(missing_ok=True)
        return 0

    for b in books:
        b["possible_duplicate"] = find_duplicate(b, conn)
        if not args.no_enrich:
            enrich(b)
    assign_themes(books, conn, use_claude=not args.no_claude)

    INBOX.mkdir(exist_ok=True)
    vocab = themes(conn)
    for b in books:
        b.pop("_subjects", None)
    PENDING_PATH.write_text(json.dumps(books, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    prior = {}
    if args.preserve_from and args.preserve_from.exists():
        prior = parse_review(args.preserve_from.read_text(encoding="utf-8"))
        kept = sum(1 for b in books if b["reading_list_id"] in prior)
        print(f"Carrying over review ticks for {kept} book(s) from {args.preserve_from}")
    REVIEW_PATH.write_text(render_review(books, vocab, prior), encoding="utf-8")
    dups = sum(1 for b in books if b["possible_duplicate"])
    print(f"Wrote {PENDING_PATH.relative_to(PENDING_PATH.parent.parent)} and "
          f"{REVIEW_PATH.relative_to(REVIEW_PATH.parent.parent)} ({dups} possible duplicate(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
