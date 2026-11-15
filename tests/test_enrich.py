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
    def __init__(self, payload=None, status=200, content=b""):
        self.status_code = status
        self._payload = payload
        self.content = content

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


def jpeg(width, height):
    """The start of a JPEG: SOI, an APP0 segment, then a baseline SOF with the size."""
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + bytes(9)
    sof = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + bytes(10)
    return b"\xff\xd8" + app0 + sof + bytes(32)


def png(width, height):
    return b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes(16)


class ImageSizeTest(unittest.TestCase):
    def test_reads_jpeg_and_png_headers(self):
        self.assertEqual(enrich.image_size(jpeg(800, 1200)), (800, 1200))
        self.assertEqual(enrich.image_size(png(200, 300)), (200, 300))

    def test_none_for_anything_else(self):
        self.assertIsNone(enrich.image_size(b"<html>not an image</html>"))
        self.assertIsNone(enrich.image_size(b""))


class BookshopCoverTest(unittest.TestCase):
    def test_accepts_a_real_cover(self):
        with mock.patch.object(enrich.requests, "get", return_value=Response(content=jpeg(800, 1200))) as get:
            url = enrich.find_bookshop_cover("978-0-226-83747-5")
        self.assertEqual(url, "https://images-us.bookshop.org/ingram/9780226837475.jpg")
        self.assertEqual(get.call_args.args[0], url)

    def test_rejects_the_placeholder_served_for_unknown_isbns(self):
        # Bookshop answers 200 with a 200x300 stand-in when it has no cover.
        with mock.patch.object(enrich.requests, "get", return_value=Response(content=jpeg(200, 300))):
            self.assertIsNone(enrich.find_bookshop_cover("9780195637243"))

    def test_rejects_errors_and_non_images(self):
        with mock.patch.object(enrich.requests, "get", return_value=Response(status=403)):
            self.assertIsNone(enrich.find_bookshop_cover("9780226837475"))
        with mock.patch.object(enrich.requests, "get", return_value=Response(content=b"<html></html>")):
            self.assertIsNone(enrich.find_bookshop_cover("9780226837475"))

    def test_needs_an_isbn13(self):
        with mock.patch.object(enrich.requests, "get") as get:
            self.assertIsNone(enrich.find_bookshop_cover("0226837475"))
            self.assertIsNone(enrich.find_bookshop_cover(None))
        get.assert_not_called()

    def test_enrich_tries_bookshop_last(self):
        book = Book(title="Bacteria to AI: Human Futures", author="N. Katherine Hayles", isbn13="9780226837475",
                    summary="s", page_count=1, publisher="p")
        with mock.patch.object(enrich, "fetch_openlibrary_by_isbn", return_value={"title": "Bacteria to AI"}), \
             mock.patch.object(enrich, "fetch_google_books", return_value=None), \
             mock.patch.object(enrich, "find_openlibrary_cover", return_value=None) as search, \
             mock.patch.object(enrich, "find_bookshop_cover", return_value="https://example.test/b.jpg") as bookshop, \
             mock.patch.object(enrich.time, "sleep"):
            enrich.enrich_book(book, save=False)
        search.assert_called_once()
        bookshop.assert_called_once_with("9780226837475")
        self.assertEqual(book.cover_url, "https://example.test/b.jpg")

    def test_enrich_skips_bookshop_when_openlibrary_search_finds_one(self):
        book = Book(title="Turbulence", author="David Szalay", isbn13="9781982122744",
                    summary="s", page_count=1, publisher="p")
        with mock.patch.object(enrich, "fetch_openlibrary_by_isbn", return_value={"title": "Turbulence"}), \
             mock.patch.object(enrich, "fetch_google_books", return_value=None), \
             mock.patch.object(enrich, "find_openlibrary_cover", return_value="https://example.test/c.jpg"), \
             mock.patch.object(enrich, "find_bookshop_cover") as bookshop, \
             mock.patch.object(enrich.time, "sleep"):
            enrich.enrich_book(book, save=False)
        bookshop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
