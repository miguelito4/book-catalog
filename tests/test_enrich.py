"""Cover lookup: the fallback that searches every edition when the matched one has no cover."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import enrich  # noqa: E402
from models import Book  # noqa: E402


class Response:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FindCoverTest(unittest.TestCase):
    def test_takes_first_result_that_has_a_cover(self):
        docs = {"docs": [{"title": "Turbulence"}, {"title": "Turbulence", "cover_i": 9201465}]}
        with mock.patch.object(enrich.requests, "get", return_value=Response(docs)) as get:
            url = enrich.find_openlibrary_cover("Turbulence", "David Szalay")
        self.assertEqual(url, "https://covers.openlibrary.org/b/id/9201465-L.jpg")
        self.assertEqual(get.call_args.kwargs["params"]["author"], "David Szalay")

    def test_searches_without_the_subtitle_and_with_the_first_author(self):
        with mock.patch.object(enrich.requests, "get", return_value=Response({"docs": []})) as get:
            url = enrich.find_openlibrary_cover("Bacteria to AI: Human Futures", "A. One; B. Two")
        self.assertIsNone(url)
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["title"], "Bacteria to AI")
        self.assertEqual(params["author"], "A. One")

    def test_enrich_falls_back_when_the_isbn_edition_has_no_cover(self):
        book = Book(title="Turbulence", author="David Szalay", isbn13="9781982122744",
                    summary="s", page_count=1, publisher="p")
        with mock.patch.object(enrich, "fetch_openlibrary_by_isbn", return_value={"title": "Turbulence"}), \
             mock.patch.object(enrich, "fetch_google_books", return_value=None), \
             mock.patch.object(enrich, "find_openlibrary_cover", return_value="https://example.test/c.jpg") as find, \
             mock.patch.object(enrich.time, "sleep"):
            enrich.enrich_book(book, save=False)
        find.assert_called_once_with("Turbulence", "David Szalay")
        self.assertEqual(book.cover_url, "https://example.test/c.jpg")


if __name__ == "__main__":
    unittest.main()
