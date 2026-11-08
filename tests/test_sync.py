"""
Offline tests for the Reading List sync: selection, duplicate detection,
review-form round trip, and apply. Runs against an in-memory copy of the
real catalog (data/books.sql); no network.

    python -m unittest discover tests
"""

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_pending  # noqa: E402
import sync_common as sc  # noqa: E402
import sync_reading_list as srl  # noqa: E402


def catalog_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "data" / "books.sql").read_bytes().decode("utf-8"))
    sc.ensure_schema(conn)
    return conn


def rl_row(rl_id, title, authors, finished, **extra):
    row = {"Reading List ID": rl_id, "Title": title, "Authors": authors,
           "Finished Reading": finished, "Did Not Finish": "", "ISBN-13": "",
           "Subjects": "", "Description": "", "Page Count": "", "Publication Date": ""}
    row.update(extra)
    return row


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = catalog_conn()
        existing = self.conn.execute(
            "SELECT id, title, author, isbn13 FROM books WHERE isbn13 IS NOT NULL ORDER BY id LIMIT 1"
        ).fetchone()
        self.existing = existing
        self.rows = [
            rl_row("NEW", "A Book Not In The Catalog Zzq", "Writer, Some", "2026-09-01",
                   Subjects="Fiction / Literary"),
            rl_row("DUP-TITLE", existing["title"], existing["author"], "2026-09-02"),
            rl_row("DUP-ISBN", "Another Edition", "Someone, Else", "2026-09-03",
                   **{"ISBN-13": existing["isbn13"]}),
            rl_row("DNF", "Abandoned Zzq", "Quitter, A", "2026-09-04", **{"Did Not Finish": "2026-09-04"}),
            rl_row("OLD", "Before Cutoff Zzq", "Early, An", "2026-08-03"),
            rl_row("ONCUTOFF", "On Cutoff Day Zzq", "Exact, An", "2026-08-04"),
            rl_row("UNFINISHED", "Still Reading Zzq", "Ongoing, An", ""),
        ]

    def test_selection_respects_cutoff_dnf_and_unfinished(self):
        ids = [b["reading_list_id"] for b in srl.candidates(self.rows, self.conn)]
        self.assertEqual(sorted(ids), ["DUP-ISBN", "DUP-TITLE", "NEW", "ONCUTOFF"])

    def test_authors_are_flipped(self):
        b = next(b for b in srl.candidates(self.rows, self.conn) if b["reading_list_id"] == "NEW")
        self.assertEqual(b["author"], "Some Writer")

    def test_duplicate_detection(self):
        books = {b["reading_list_id"]: b for b in srl.candidates(self.rows, self.conn)}
        self.assertIsNone(srl.find_duplicate(books["NEW"], self.conn))
        self.assertEqual(srl.find_duplicate(books["DUP-TITLE"], self.conn)["id"], self.existing["id"])
        dup = srl.find_duplicate(books["DUP-ISBN"], self.conn)
        self.assertEqual((dup["id"], dup["reason"]), (self.existing["id"], "same ISBN-13"))

    def test_normalization(self):
        self.assertEqual(sc.norm_title("The Rings of Saturn: A Walk"), "rings of saturn")
        self.assertEqual(sc.author_surname("Sebald, W. G."), "sebald")
        self.assertEqual(sc.author_surname("W. G. Sebald"), "sebald")
        self.assertEqual(sc.author_surname("Gabriel García Márquez"), "marquez")

    def test_review_round_trip(self):
        books = srl.candidates(self.rows, self.conn)
        for b in books:
            b["possible_duplicate"] = srl.find_duplicate(b, self.conn)
            b["suggested_themes"] = ["fiction"] if b["reading_list_id"] == "NEW" else []
        md = sc.render_review(books, sc.themes(self.conn))
        d = sc.parse_review(md)
        self.assertEqual(d["NEW"], {"themes": ["fiction"], "recommended": False, "skip": False, "link": None,
                                    "title": "A Book Not In The Catalog Zzq", "author": "Some Writer"})
        self.assertEqual(d["DUP-TITLE"]["link"], self.existing["id"])
        # every theme in the vocabulary is offered for every book
        self.assertEqual(md.count("<!-- t:"), len(books) * len(sc.themes(self.conn)))

    def test_apply(self):
        books = srl.candidates(self.rows, self.conn)
        for b in books:
            b["possible_duplicate"] = srl.find_duplicate(b, self.conn)
            b["suggested_themes"] = []
        md = sc.render_review(books, sc.themes(self.conn))
        # Reviewer: theme + star on NEW, skip the ISBN duplicate, keep the title link.
        lines, current = [], None
        for line in md.splitlines():
            if "<!-- rl:" in line:
                current = line.split("rl:")[1].split()[0]
            if current == "NEW" and ("t:history" in line or "f:recommended" in line):
                line = line.replace("[ ]", "[x]")
            if current == "ONCUTOFF" and "t:fiction" in line:
                line = line.replace("[ ]", "[x]")
            if current == "DUP-ISBN" and "f:link:" in line:
                line = line.replace("[x]", "[ ]")
            if current == "DUP-ISBN" and "f:skip" in line:
                line = line.replace("[ ]", "[x]")
            lines.append(line)
        before = self.conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        with self.conn:
            summary = apply_pending.apply(books, sc.parse_review("\n".join(lines)), self.conn)

        self.assertEqual(len(summary["added"]), 2)            # NEW + ONCUTOFF
        self.assertEqual(len(summary["linked"]), 1)
        self.assertEqual(summary["skipped"], ["Another Edition"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM books").fetchone()[0], before + 2)
        new = self.conn.execute(
            """SELECT b.date_read, b.year_read, b.is_recommended, group_concat(t.slug) AS themes
               FROM books b JOIN book_themes bt ON bt.book_id = b.id JOIN themes t ON t.id = bt.theme_id
               WHERE b.reading_list_id = 'NEW'"""
        ).fetchone()
        self.assertEqual(tuple(new), ("2026-09-01", 2026, 1, "history"))
        linked = self.conn.execute("SELECT reading_list_id FROM books WHERE id = ?",
                                   (self.existing["id"],)).fetchone()[0]
        self.assertEqual(linked, "DUP-TITLE")
        # A second sync finds nothing: added/linked by id, skipped via sync_skips.
        self.assertEqual(srl.candidates(self.rows, self.conn), [])

    def test_apply_rejects_unknown_theme(self):
        books = [b for b in srl.candidates(self.rows, self.conn) if b["reading_list_id"] == "NEW"]
        decisions = {"NEW": {"themes": ["not-a-theme"], "recommended": False, "skip": False, "link": None,
                             "title": None, "author": None}}
        with self.assertRaises(apply_pending.ReviewError):
            apply_pending.apply(books, decisions, self.conn)

    def test_apply_requires_a_theme_for_added_books(self):
        books = [b for b in srl.candidates(self.rows, self.conn) if b["reading_list_id"] == "NEW"]
        decisions = {"NEW": {"themes": [], "recommended": True, "skip": False, "link": None,
                             "title": None, "author": None}}
        with self.assertRaisesRegex(apply_pending.ReviewError, "No theme ticked"):
            apply_pending.apply(books, decisions, self.conn)
        # ...but a skipped book needs none
        decisions["NEW"]["skip"] = True
        self.assertEqual(apply_pending.apply(books, decisions, self.conn)["skipped"], [books[0]["title"]])

    def test_resync_preserves_review_ticks(self):
        books = srl.candidates(self.rows, self.conn)
        for b in books:
            b["possible_duplicate"] = srl.find_duplicate(b, self.conn)
            b["suggested_themes"] = ["fiction"]
        vocab = sc.themes(self.conn)
        first = sc.render_review(books, vocab)
        # Reviewer swaps NEW to history + star and unlinks DUP-TITLE.
        edited, current = [], None
        for line in first.splitlines():
            if "<!-- rl:" in line:
                current = line.split("rl:")[1].split()[0]
            if current == "NEW" and "t:fiction" in line:
                line = line.replace("[x]", "[ ]")
            if current == "NEW" and ("t:history" in line or "f:recommended" in line):
                line = line.replace("[ ]", "[x]")
            if current == "DUP-TITLE" and "f:link:" in line:
                line = line.replace("[x]", "[ ]")
            edited.append(line)
        prior = sc.parse_review("\n".join(edited))
        # A new export arrives with one more book; suggestions differ this time.
        more = books + [dict(books[0], reading_list_id="LATER", title="Later Book Zzq",
                             possible_duplicate=None)]
        for b in more:
            b["suggested_themes"] = ["poetry"]
        d = sc.parse_review(sc.render_review(more, vocab, prior))
        self.assertEqual(d["NEW"]["themes"], ["history"])
        self.assertTrue(d["NEW"]["recommended"])
        self.assertIsNone(d["DUP-TITLE"]["link"])
        self.assertEqual(d["LATER"]["themes"], ["poetry"])       # new book gets fresh suggestions

    def test_reviewer_can_edit_title_and_author(self):
        books = [b for b in srl.candidates(self.rows, self.conn) if b["reading_list_id"] == "NEW"]
        for b in books:
            b["possible_duplicate"], b["suggested_themes"] = None, ["fiction"]
        md = sc.render_review(books, sc.themes(self.conn))
        md = md.replace("Title: A Book Not In The Catalog Zzq", "Title: A Corrected Title Zzq")
        md = md.replace("Author: Some Writer", "Author: Some K. Writer")
        d = sc.parse_review(md)
        with self.conn:
            apply_pending.apply(books, d, self.conn)
        row = self.conn.execute("SELECT title, author FROM books WHERE reading_list_id = 'NEW'").fetchone()
        self.assertEqual(tuple(row), ("A Corrected Title Zzq", "Some K. Writer"))
        # edits survive a re-sync
        again = sc.parse_review(sc.render_review(books, sc.themes(self.conn), d))
        self.assertEqual(again["NEW"]["title"], "A Corrected Title Zzq")

    def test_cleaning_reading_list_metadata(self):
        cases = {
            "Szalay, David": "David Szalay",
            "Kleist, Heinrich von": "Heinrich von Kleist",
            "Joyce, Appleby\\,": "Joyce Appleby",                    # mangled credited name
            "Katherine, Hayles\\, N.": "N. Katherine Hayles",
            "manager), Hartnett\\, Kevin (Hubble science operations": "Kevin Hartnett",
            "Ph.D., Dan Kindlon\\,; PhD, Michael Thompson\\,": "Dan Kindlon; Michael Thompson",
            "Jr., Henry Louis Gates\\,": "Henry Louis Gates Jr.",
            "Polybius\\,": "Polybius",
        }
        for raw, want in cases.items():
            self.assertEqual(sc.clean_author(raw), want, raw)
        titles = {
            "All That Man Is A Novel": "All That Man Is",
            "Apeirogon: A Novel": "Apeirogon",
            "The relentless revolution: a history of capitalism":
                "The Relentless Revolution: A History of Capitalism",
            "Bacteria to AI: human futures with our nonhuman symbionts":
                "Bacteria to AI: Human Futures with Our Nonhuman Symbionts",
            "The Remains of the Day": "The Remains of the Day",
            "A Novel Approach to Things": "A Novel Approach to Things",
        }
        for raw, want in titles.items():
            self.assertEqual(sc.clean_title(raw), want, raw)

    def test_apply_requires_a_decision_for_every_book(self):
        books = srl.candidates(self.rows, self.conn)
        with self.assertRaises(apply_pending.ReviewError):
            apply_pending.apply(books, {}, self.conn)


if __name__ == "__main__":
    unittest.main()
