#!/usr/bin/env python3
"""
Apply a reviewed batch: inbox/pending.json + the checkbox state of the review
form (the merged PR description, or inbox/review.md locally).

For each book:
  - "Already in catalog" checked -> link the existing entry (sets reading_list_id)
  - "Skip" checked               -> remember the skip so it never comes back
  - otherwise                    -> insert with the ticked themes and ⭐ flag

Then removes the inbox files and refreshes catalog.json and books.sql.
Runs in one transaction: any validation error leaves the database untouched.

Usage:
    python scripts/apply_pending.py                         # uses inbox/review.md
    python scripts/apply_pending.py --review pr_body.md     # what the Action does
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sync_common import (  # noqa: E402
    PENDING_PATH, REVIEW_PATH, ROOT, connect, ensure_schema, parse_review, themes,
)

BOOK_FIELDS = [
    "reading_list_id", "title", "subtitle", "author", "isbn13", "openlibrary_key",
    "year_published", "language", "publisher", "page_count", "cover_url", "summary",
    "date_started", "date_read",
]


class ReviewError(Exception):
    pass


def apply(pending: list[dict], decisions: dict, conn) -> dict:
    vocab = {t["slug"] for t in themes(conn)}
    theme_ids = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM themes")}
    today = date.today().isoformat()
    summary = {"added": [], "linked": [], "skipped": [], "recommended": []}

    missing = [p["title"] for p in pending if p["reading_list_id"] not in decisions]
    if missing:
        raise ReviewError("No review section found for: " + "; ".join(missing))

    for p in pending:
        d = decisions[p["reading_list_id"]]
        bad = [t for t in d["themes"] if t not in vocab]
        if bad:
            raise ReviewError(f"Unknown theme(s) {bad} on '{p['title']}'")

        if d["link"]:
            row = conn.execute("SELECT id, title, reading_list_id FROM books WHERE id = ?",
                               (d["link"],)).fetchone()
            if not row:
                raise ReviewError(f"'{p['title']}' links to book #{d['link']}, which doesn't exist")
            if row["reading_list_id"] not in (None, p["reading_list_id"]):
                raise ReviewError(f"Book #{row['id']} is already linked to another Reading List entry")
            # Link, and fill a missing finish date from Reading List (never overwrite).
            conn.execute(
                """UPDATE books SET reading_list_id = ?,
                       date_read = COALESCE(date_read, ?),
                       year_read = COALESCE(year_read, ?)
                   WHERE id = ?""",
                (p["reading_list_id"], p["date_read"], int(p["date_read"][:4]), row["id"]),
            )
            if d["recommended"]:
                conn.execute("UPDATE books SET is_recommended = 1 WHERE id = ?", (row["id"],))
                summary["recommended"].append(row["title"])
            summary["linked"].append(f"{p['title']} -> #{row['id']}")
            continue

        if not (d.get("title") or p["title"]).strip():
            raise ReviewError(f"Empty title for Reading List entry {p['reading_list_id']}")

        if d["skip"]:
            conn.execute("INSERT OR REPLACE INTO sync_skips (reading_list_id, title) VALUES (?, ?)",
                         (p["reading_list_id"], p["title"]))
            summary["skipped"].append(p["title"])
            continue

        if not d["themes"]:
            raise ReviewError(f"No theme ticked for '{p['title']}'. Tick at least one, or Skip it.")

        values = {k: p.get(k) for k in BOOK_FIELDS}
        values["title"] = d.get("title") or p["title"]          # reviewer edits win
        values["author"] = d.get("author") or p.get("author")
        values.update(
            reading_status="read",
            year_read=int(p["date_read"][:4]),
            date_added=today,
            is_recommended=1 if d["recommended"] else 0,
        )
        cols = ", ".join(values)
        cur = conn.execute(f"INSERT INTO books ({cols}) VALUES ({', '.join('?' * len(values))})",
                           list(values.values()))
        for slug in d["themes"]:
            conn.execute("INSERT OR IGNORE INTO book_themes (book_id, theme_id) VALUES (?, ?)",
                         (cur.lastrowid, theme_ids[slug]))
        summary["added"].append(f"{values['title']} ({values['author']}) [{', '.join(d['themes'])}]")
        if d["recommended"]:
            summary["recommended"].append(p["title"])
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply a reviewed Reading List batch")
    ap.add_argument("--review", type=Path, default=REVIEW_PATH, help="Review form markdown")
    ap.add_argument("--pending", type=Path, default=PENDING_PATH)
    ap.add_argument("--no-export", action="store_true", help="Skip catalog.json / books.sql refresh")
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate the review and report what would happen; change nothing")
    args = ap.parse_args()

    if not args.pending.exists():
        print("Nothing to apply (no inbox/pending.json).")
        return 0

    pending = json.loads(args.pending.read_text(encoding="utf-8"))
    decisions = parse_review(args.review.read_text(encoding="utf-8"))

    conn = connect()
    ensure_schema(conn)
    try:
        if args.dry_run:
            summary = apply(pending, decisions, conn)
            conn.rollback()
        else:
            with conn:  # one transaction
                summary = apply(pending, decisions, conn)
    except ReviewError as e:
        print(f"Review error, nothing applied: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    for k, items in summary.items():
        if items:
            print(f"{k.capitalize()} ({len(items)}):")
            for i in items:
                print(f"  - {i}")

    if args.dry_run:
        print("Dry run: review is valid, nothing changed.")
        return 0

    args.pending.unlink(missing_ok=True)
    REVIEW_PATH.unlink(missing_ok=True)

    if not args.no_export:
        sys.stdout.flush()  # keep the summary first when output is piped (commit messages)
        for script in ("export.py", "db_dump.py"):
            subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True,
                           stdout=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
