#!/usr/bin/env python3
"""
Enrich book metadata from external APIs.

Uses OpenLibrary (primary) and Google Books (fallback) to fetch:
- Cover images
- Descriptions/summaries
- Page counts
- Publisher info
- Subject/category data

Covers are looked for in order: the OpenLibrary edition matched by ISBN,
Google Books, an OpenLibrary search across editions, then Bookshop.org by
ISBN-13.

Usage:
    python enrich.py              # Enrich all books missing metadata
    python enrich.py --book-id 1  # Enrich specific book
    python enrich.py --force      # Re-enrich even if metadata exists
"""

import argparse
import time
import requests
from typing import Optional, Dict, Any

from models import Book, BookDB


# API endpoints
OPENLIBRARY_ISBN_API = "https://openlibrary.org/isbn/{isbn}.json"
OPENLIBRARY_SEARCH_API = "https://openlibrary.org/search.json"
OPENLIBRARY_WORKS_API = "https://openlibrary.org{works_key}.json"
OPENLIBRARY_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"

GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"

# Bookshop.org's cover image service, keyed by ISBN-13. It answers 200 for any
# ISBN: an unknown one gets a 200x300 placeholder image, not an error, so a
# hit has to be judged by the image itself (see find_bookshop_cover).
BOOKSHOP_COVER_URL = "https://images-us.bookshop.org/ingram/{isbn13}.jpg"
BOOKSHOP_MIN_WIDTH = 300

# Rate limiting
REQUEST_DELAY = 1.0  # seconds between API calls


def fetch_openlibrary_by_isbn(isbn: str) -> Optional[Dict[str, Any]]:
    """Fetch book data from OpenLibrary by ISBN."""
    try:
        url = OPENLIBRARY_ISBN_API.format(isbn=isbn)
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None
        else:
            print(f"  OpenLibrary ISBN lookup failed: {response.status_code}")
            return None
    except requests.RequestException as e:
        print(f"  OpenLibrary request error: {e}")
        return None


def fetch_openlibrary_by_title_author(title: str, author: str = None) -> Optional[Dict[str, Any]]:
    """Search OpenLibrary by title and author."""
    try:
        params = {"title": title, "limit": 1}
        if author:
            params["author"] = author
        
        response = requests.get(OPENLIBRARY_SEARCH_API, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("docs"):
                return data["docs"][0]
        return None
    except requests.RequestException as e:
        print(f"  OpenLibrary search error: {e}")
        return None


def find_openlibrary_cover(title: str, author: str = None) -> Optional[str]:
    """
    Search OpenLibrary by title and author for any edition's cover.

    The ISBN lookup returns one edition, and many edition records carry no
    cover even when the work has one. This looks across the search results
    and returns the first cover found. The subtitle is dropped from the query:
    OpenLibrary titles rarely include it, so searching with it misses.
    """
    try:
        params = {"title": title.split(":")[0].strip(), "limit": 5, "fields": "cover_i,title"}
        if author:
            params["author"] = author.split(";")[0].strip()

        response = requests.get(OPENLIBRARY_SEARCH_API, params=params, timeout=10)
        if response.status_code != 200:
            return None
        for doc in response.json().get("docs", []):
            if doc.get("cover_i"):
                return OPENLIBRARY_COVER_URL.format(cover_id=doc["cover_i"])
        return None
    except requests.RequestException as e:
        print(f"  OpenLibrary cover search error: {e}")
        return None


def image_size(data: bytes) -> Optional[tuple]:
    """Width and height of a JPEG or PNG, read from its header. None if neither."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte before a marker
            i += 1
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        # Start-of-frame markers carry the dimensions (C4, C8 and CC are not SOFs).
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    return None


def find_bookshop_cover(isbn13: str) -> Optional[str]:
    """
    Cover from Bookshop.org's image service, by ISBN-13.

    The service never says "not found": an ISBN it doesn't have gets a small
    placeholder image with a 200 status. So the image is downloaded and
    accepted only if it is a real picture at least BOOKSHOP_MIN_WIDTH wide.
    """
    digits = "".join(ch for ch in (isbn13 or "") if ch.isdigit())
    if len(digits) != 13:
        return None
    url = BOOKSHOP_COVER_URL.format(isbn13=digits)
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return None
        size = image_size(response.content)
        if not size or size[0] < BOOKSHOP_MIN_WIDTH:
            return None
        return url
    except requests.RequestException as e:
        print(f"  Bookshop cover error: {e}")
        return None


def fetch_openlibrary_works(works_key: str) -> Optional[Dict[str, Any]]:
    """Fetch work details (for description) from OpenLibrary."""
    try:
        url = OPENLIBRARY_WORKS_API.format(works_key=works_key)
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        return None
    except requests.RequestException as e:
        print(f"  OpenLibrary works error: {e}")
        return None


def fetch_google_books(isbn: str = None, title: str = None, author: str = None) -> Optional[Dict[str, Any]]:
    """Fetch book data from Google Books API."""
    try:
        if isbn:
            query = f"isbn:{isbn}"
        elif title and author:
            query = f"intitle:{title} inauthor:{author}"
        elif title:
            query = f"intitle:{title}"
        else:
            return None
        
        params = {"q": query, "maxResults": 1}
        response = requests.get(GOOGLE_BOOKS_API, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("items"):
                return data["items"][0].get("volumeInfo", {})
        return None
    except requests.RequestException as e:
        print(f"  Google Books error: {e}")
        return None


def extract_description(data: Dict[str, Any], source: str) -> Optional[str]:
    """Extract description from API response."""
    if source == "openlibrary":
        # OpenLibrary stores descriptions in various formats
        desc = data.get("description")
        if isinstance(desc, dict):
            return desc.get("value")
        elif isinstance(desc, str):
            return desc
    elif source == "google":
        return data.get("description")
    return None


def extract_cover_url(data: Dict[str, Any], source: str) -> Optional[str]:
    """Extract cover image URL from API response."""
    if source == "openlibrary":
        # From ISBN lookup - covers are IDs
        covers = data.get("covers", [])
        if covers:
            return OPENLIBRARY_COVER_URL.format(cover_id=covers[0])
        # From search - cover_i is the ID
        cover_id = data.get("cover_i")
        if cover_id:
            return OPENLIBRARY_COVER_URL.format(cover_id=cover_id)
    elif source == "google":
        image_links = data.get("imageLinks", {})
        # Prefer larger images
        for key in ["large", "medium", "thumbnail"]:
            if key in image_links:
                # Remove zoom parameter for better quality
                url = image_links[key].replace("&edge=curl", "")
                return url.replace("zoom=1", "zoom=2")
    return None


def enrich_book(book: Book, force: bool = False, save: bool = True) -> bool:
    """
    Enrich a single book with metadata from external APIs.
    Returns True if any data was updated. With save=False the Book is only
    updated in memory (used by sync_reading_list.py before a book is in the DB).
    """
    print(f"Enriching: {book.title} by {book.author or 'Unknown'}")
    
    updated = False
    
    # Determine what we need
    needs_cover = force or not book.cover_url
    needs_summary = force or not book.summary
    needs_page_count = force or not book.page_count
    needs_publisher = force or not book.publisher
    
    if not any([needs_cover, needs_summary, needs_page_count, needs_publisher]):
        print("  Already complete, skipping")
        return False
    
    # Strategy: Try OpenLibrary first (free, no API key), then Google Books
    ol_data = None
    ol_works_data = None
    google_data = None
    
    # Try OpenLibrary by ISBN
    isbn = book.isbn13 or book.isbn
    if isbn:
        print(f"  Trying OpenLibrary (ISBN: {isbn})...")
        ol_data = fetch_openlibrary_by_isbn(isbn)
        time.sleep(REQUEST_DELAY)
    
    # Fallback: OpenLibrary search by title/author
    if not ol_data and book.title:
        print(f"  Trying OpenLibrary search...")
        ol_data = fetch_openlibrary_by_title_author(book.title, book.author)
        time.sleep(REQUEST_DELAY)
    
    # If we got OpenLibrary data, fetch the works record for description
    if ol_data:
        works_key = None
        # From ISBN lookup
        if "works" in ol_data and ol_data["works"]:
            works_key = ol_data["works"][0].get("key")
        # From search
        elif "key" in ol_data:
            works_key = ol_data.get("key")
        
        if works_key and needs_summary:
            print(f"  Fetching work details...")
            ol_works_data = fetch_openlibrary_works(works_key)
            time.sleep(REQUEST_DELAY)
    
    # Try Google Books as supplement/fallback
    if needs_cover or needs_summary:
        print(f"  Trying Google Books...")
        google_data = fetch_google_books(isbn=isbn, title=book.title, author=book.author)
        time.sleep(REQUEST_DELAY)
    
    # Extract and apply data
    
    # Cover URL (prefer OpenLibrary for quality)
    if needs_cover:
        cover = None
        if ol_data:
            cover = extract_cover_url(ol_data, "openlibrary")
        if not cover and google_data:
            cover = extract_cover_url(google_data, "google")
        # Last resort: the edition we matched has no cover; look for one on
        # any edition of the work.
        if not cover and book.title:
            print(f"  Searching OpenLibrary for a cover...")
            cover = find_openlibrary_cover(book.title, book.author)
            time.sleep(REQUEST_DELAY)
        # Third backup: Bookshop.org, by ISBN-13.
        if not cover and book.isbn13:
            print(f"  Trying Bookshop.org for a cover...")
            cover = find_bookshop_cover(book.isbn13)
            time.sleep(REQUEST_DELAY)
        
        if cover:
            book.cover_url = cover
            updated = True
            print(f"  Found cover")
    
    # Summary/description
    if needs_summary:
        summary = None
        # Try OpenLibrary works data first
        if ol_works_data:
            summary = extract_description(ol_works_data, "openlibrary")
        # Fallback to Google Books
        if not summary and google_data:
            summary = extract_description(google_data, "google")
        
        if summary:
            book.summary = summary
            updated = True
            print(f"  Found summary ({len(summary)} chars)")
    
    # Page count
    if needs_page_count:
        page_count = None
        if ol_data and ol_data.get("number_of_pages"):
            page_count = ol_data["number_of_pages"]
        elif google_data and google_data.get("pageCount"):
            page_count = google_data["pageCount"]
        
        if page_count:
            book.page_count = page_count
            updated = True
            print(f"  Found page count: {page_count}")
    
    # Publisher
    if needs_publisher:
        publisher = None
        if ol_data:
            publishers = ol_data.get("publishers", [])
            if publishers:
                publisher = publishers[0] if isinstance(publishers[0], str) else publishers[0].get("name")
        elif google_data:
            publisher = google_data.get("publisher")
        
        if publisher:
            book.publisher = publisher
            updated = True
            print(f"  Found publisher: {publisher}")
    
    # Store OpenLibrary key for future reference
    if ol_data and not book.openlibrary_key:
        key = ol_data.get("key")
        if key:
            book.openlibrary_key = key
            updated = True
    
    # Save if we found anything
    if updated and save:
        BookDB.update(book)
        print(f"  Saved updates")
    else:
        print(f"  No new data found")
    
    return updated


def main():
    parser = argparse.ArgumentParser(description="Enrich book metadata from external APIs")
    parser.add_argument("--book-id", type=int, help="Enrich specific book by ID")
    parser.add_argument("--force", action="store_true", help="Re-enrich even if metadata exists")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be enriched without making changes")
    args = parser.parse_args()
    
    if args.book_id:
        # Enrich single book
        book = BookDB.get(args.book_id)
        if not book:
            print(f"Book not found: {args.book_id}")
            return
        
        if args.dry_run:
            print(f"Would enrich: {book.title}")
            print(f"  Has cover: {bool(book.cover_url)}")
            print(f"  Has summary: {bool(book.summary)}")
            print(f"  Has page count: {bool(book.page_count)}")
        else:
            enrich_book(book, force=args.force)
    else:
        # Enrich all books needing it
        if args.force:
            books = BookDB.get_all()
        else:
            books = BookDB.get_needing_enrichment()
        
        if not books:
            print("No books need enrichment")
            return
        
        print(f"Found {len(books)} books to enrich\n")
        
        if args.dry_run:
            for book in books:
                print(f"Would enrich: {book.title}")
            return
        
        enriched = 0
        for book in books:
            if enrich_book(book, force=args.force):
                enriched += 1
            print()
        
        print(f"\nEnrichment complete: {enriched}/{len(books)} books updated")


if __name__ == "__main__":
    main()
