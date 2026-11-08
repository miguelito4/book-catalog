#!/usr/bin/env python3
"""
Dump data/books.db to data/books.sql, the committed source of truth.

The SQLite file is a build artifact (gitignored); books.sql is what lives in
git, so every catalog change is a readable, line-per-row diff.

Usage:
    python scripts/db_dump.py              # books.db -> books.sql
    python scripts/db_dump.py --check      # exit 1 if books.sql is stale
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "books.db"
SQL_PATH = ROOT / "data" / "books.sql"


def dump(db_path: Path = DB_PATH) -> str:
    conn = sqlite3.connect(db_path)
    try:
        # iterdump emits schema then rows in rowid order: deterministic,
        # one INSERT per line.
        return "\n".join(conn.iterdump()) + "\n"
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--check", action="store_true",
                        help="Fail if books.sql doesn't match books.db")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}. Run scripts/db_load.py first.", file=sys.stderr)
        return 1

    sql = dump()
    if args.check:
        current = SQL_PATH.read_bytes().decode("utf-8") if SQL_PATH.exists() else ""
        if current != sql:
            print("books.sql is out of date. Run: python scripts/db_dump.py", file=sys.stderr)
            return 1
        print("books.sql is up to date.")
        return 0

    # Bytes, not text mode: some summaries contain \r\n that must survive verbatim.
    SQL_PATH.write_bytes(sql.encode("utf-8"))
    print(f"Dumped {DB_PATH.name} -> {SQL_PATH.relative_to(ROOT)} ({len(sql.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
