#!/usr/bin/env python3
"""
CI guard: confirm site/_data/catalog.json matches what export.py produces
from the database (ignoring the generated_at timestamp).

Catches a books.sql change that wasn't followed by an export, or a hand-edited
catalog.json that has drifted from the database.

Usage:
    python scripts/check_catalog.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
COMMITTED = ROOT / "site" / "_data" / "catalog.json"


def strip(d: dict) -> dict:
    d = dict(d)
    d.pop("generated_at", None)
    return d


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "catalog.json"
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "export.py"), "--output", str(out)],
            check=True, stdout=subprocess.DEVNULL,
        )
        fresh = strip(json.loads(out.read_text(encoding="utf-8")))

    committed = strip(json.loads(COMMITTED.read_text(encoding="utf-8")))
    if fresh != committed:
        print("catalog.json does not match the database. Run: python scripts/export.py", file=sys.stderr)
        print(f"  committed: {committed.get('stats')}", file=sys.stderr)
        print(f"  database:  {fresh.get('stats')}", file=sys.stderr)
        return 1
    print(f"catalog.json matches the database ({fresh['stats']['total_books']} books).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
