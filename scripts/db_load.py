#!/usr/bin/env python3
"""
Rebuild data/books.db from the committed data/books.sql.

Run this after cloning or pulling, and in CI before export/build.

Usage:
    python scripts/db_load.py           # refuses to overwrite an existing books.db
    python scripts/db_load.py --force   # replace books.db with what's in git
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "books.db"
SQL_PATH = ROOT / "data" / "books.sql"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing books.db (local changes not yet dumped are lost)")
    args = parser.parse_args()

    if not SQL_PATH.exists():
        print(f"No dump at {SQL_PATH}", file=sys.stderr)
        return 1
    if DB_PATH.exists() and DB_PATH.stat().st_size > 0 and not args.force:
        print(f"{DB_PATH} already exists. Use --force to replace it with books.sql.", file=sys.stderr)
        return 1

    tmp = DB_PATH.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        # Bytes, not text mode: preserve \r\n inside string literals.
        conn.executescript(SQL_PATH.read_bytes().decode("utf-8"))
        conn.commit()
    finally:
        conn.close()
    tmp.replace(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    conn.close()
    print(f"Loaded {SQL_PATH.relative_to(ROOT)} -> {DB_PATH.name} ({n} books)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
