#!/usr/bin/env python3
"""
Shared database models and utilities for the book catalog.

Provides a clean interface to the SQLite database for use by CLI, enrichment, and export scripts.
"""

import sqlite3
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from datetime import date, datetime
from contextlib import contextmanager

# Database location
DB_PATH = Path(__file__).parent.parent / "data" / "books.db"


@dataclass
class Book:
    """Represents a book in the catalog."""
    id: Optional[int] = None
    
    # Identifiers
    isbn: Optional[str] = None
    isbn13: Optional[str] = None
    openlibrary_key: Optional[str] = None
    
    # Core metadata
    title: str = ""
    subtitle: Optional[str] = None
    author: Optional[str] = None
    additional_authors: Optional[str] = None
    translator: Optional[str] = None
    year_published: Optional[int] = None
    original_year: Optional[int] = None
    language: Optional[str] = None
    original_language: Optional[str] = None
    
    # Edition details
    publisher: Optional[str] = None
    page_count: Optional[int] = None
    format: Optional[str] = None
    
    # Enriched metadata
    cover_url: Optional[str] = None
    summary: Optional[str] = None
    
    # Reading record
    reading_status: str = "read"
    date_started: Optional[date] = None
    date_read: Optional[date] = None
    year_read: Optional[int] = None
    reread: int = 0
    
    # Assessment
    is_recommended: bool = False
    my_notes: Optional[str] = None
    my_summary: Optional[str] = None
    reading_context: Optional[str] = None
    
    # Series
    series_name: Optional[str] = None
    series_position: Optional[float] = None
    
    # Housekeeping
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Related data (populated separately)
    themes: List[str] = field(default_factory=list)
    links: List[dict] = field(default_factory=list)


@dataclass
class Theme:
    """Represents a theme/category."""
    id: Optional[int] = None
    name: str = ""
    slug: str = ""
    description: Optional[str] = None
    display_order: Optional[int] = None


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()


class BookDB:
    """Database operations for books."""
    
    @staticmethod
    def add(book: Book) -> int:
        """Add a new book. Returns the new book ID."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO books (
                    isbn, isbn13, openlibrary_key,
                    title, subtitle, author, additional_authors, translator,
                    year_published, original_year, language, original_language,
                    publisher, page_count, format,
                    cover_url, summary,
                    reading_status, date_started, date_read, year_read, reread,
                    is_recommended, my_notes, my_summary, reading_context,
                    series_name, series_position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                book.isbn, book.isbn13, book.openlibrary_key,
                book.title, book.subtitle, book.author, book.additional_authors, book.translator,
                book.year_published, book.original_year, book.language, book.original_language,
                book.publisher, book.page_count, book.format,
                book.cover_url, book.summary,
                book.reading_status, book.date_started, book.date_read, book.year_read, book.reread,
                book.is_recommended, book.my_notes, book.my_summary, book.reading_context,
                book.series_name, book.series_position
            ))
            conn.commit()
            return cursor.lastrowid
    
    @staticmethod
    def update(book: Book) -> None:
        """Update an existing book."""
        if not book.id:
            raise ValueError("Book must have an ID to update")
        
        with get_db() as conn:
            conn.execute("""
                UPDATE books SET
                    isbn = ?, isbn13 = ?, openlibrary_key = ?,
                    title = ?, subtitle = ?, author = ?, additional_authors = ?, translator = ?,
                    year_published = ?, original_year = ?, language = ?, original_language = ?,
                    publisher = ?, page_count = ?, format = ?,
                    cover_url = ?, summary = ?,
                    reading_status = ?, date_started = ?, date_read = ?, year_read = ?, reread = ?,
                    is_recommended = ?, my_notes = ?, my_summary = ?, reading_context = ?,
                    series_name = ?, series_position = ?
                WHERE id = ?
            """, (
                book.isbn, book.isbn13, book.openlibrary_key,
                book.title, book.subtitle, book.author, book.additional_authors, book.translator,
                book.year_published, book.original_year, book.language, book.original_language,
                book.publisher, book.page_count, book.format,
                book.cover_url, book.summary,
                book.reading_status, book.date_started, book.date_read, book.year_read, book.reread,
                book.is_recommended, book.my_notes, book.my_summary, book.reading_context,
                book.series_name, book.series_position,
                book.id
            ))
            conn.commit()
    
    @staticmethod
    def get(book_id: int) -> Optional[Book]:
        """Get a book by ID."""
        with get_db() as conn:
            row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            if row:
                return BookDB._row_to_book(row)
        return None
    
    @staticmethod
    def get_by_isbn(isbn: str) -> Optional[Book]:
        """Get a book by ISBN (checks both isbn and isbn13)."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE isbn = ? OR isbn13 = ?", 
                (isbn, isbn)
            ).fetchone()
            if row:
                return BookDB._row_to_book(row)
        return None
    
    @staticmethod
    def get_all(include_themes: bool = True, include_links: bool = False) -> List[Book]:
        """Get all books, optionally with themes and links."""
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM books ORDER BY author, title").fetchall()
            books = [BookDB._row_to_book(row) for row in rows]
            
            if include_themes:
                for book in books:
                    book.themes = BookDB.get_themes(book.id)
            
            if include_links:
                for book in books:
                    book.links = BookDB.get_links(book.id)
            
            return books
    
    @staticmethod
    def get_needing_enrichment() -> List[Book]:
        """Get books that are missing enrichable metadata."""
        with get_db() as conn:
            rows = conn.execute("""
                SELECT * FROM books 
                WHERE (cover_url IS NULL OR summary IS NULL)
                AND (isbn IS NOT NULL OR isbn13 IS NOT NULL OR (title IS NOT NULL AND author IS NOT NULL))
                ORDER BY created_at DESC
            """).fetchall()
            return [BookDB._row_to_book(row) for row in rows]
    
    @staticmethod
    def delete(book_id: int) -> None:
        """Delete a book by ID."""
        with get_db() as conn:
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            conn.commit()
    
    @staticmethod
    def add_theme(book_id: int, theme_slug: str) -> None:
        """Add a theme to a book."""
        with get_db() as conn:
            theme = conn.execute(
                "SELECT id FROM themes WHERE slug = ?", (theme_slug,)
            ).fetchone()
            if not theme:
                raise ValueError(f"Theme not found: {theme_slug}")
            
            conn.execute(
                "INSERT OR IGNORE INTO book_themes (book_id, theme_id) VALUES (?, ?)",
                (book_id, theme["id"])
            )
            conn.commit()
    
    @staticmethod
    def remove_theme(book_id: int, theme_slug: str) -> None:
        """Remove a theme from a book."""
        with get_db() as conn:
            theme = conn.execute(
                "SELECT id FROM themes WHERE slug = ?", (theme_slug,)
            ).fetchone()
            if theme:
                conn.execute(
                    "DELETE FROM book_themes WHERE book_id = ? AND theme_id = ?",
                    (book_id, theme["id"])
                )
                conn.commit()
    
    @staticmethod
    def get_themes(book_id: int) -> List[str]:
        """Get theme slugs for a book."""
        with get_db() as conn:
            rows = conn.execute("""
                SELECT t.slug FROM themes t
                JOIN book_themes bt ON t.id = bt.theme_id
                WHERE bt.book_id = ?
                ORDER BY t.display_order
            """, (book_id,)).fetchall()
            return [row["slug"] for row in rows]
    
    @staticmethod
    def add_link(book_id: int, link_type: str, url: str, title: str = None, notes: str = None) -> int:
        """Add a link to a book."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO book_links (book_id, link_type, url, title, notes) VALUES (?, ?, ?, ?, ?)",
                (book_id, link_type, url, title, notes)
            )
            conn.commit()
            return cursor.lastrowid
    
    @staticmethod
    def get_links(book_id: int) -> List[dict]:
        """Get links for a book."""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM book_links WHERE book_id = ?", (book_id,)
            ).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def _row_to_book(row: sqlite3.Row) -> Book:
        """Convert a database row to a Book object."""
        return Book(
            id=row["id"],
            isbn=row["isbn"],
            isbn13=row["isbn13"],
            openlibrary_key=row["openlibrary_key"],
            title=row["title"],
            subtitle=row["subtitle"],
            author=row["author"],
            additional_authors=row["additional_authors"],
            translator=row["translator"],
            year_published=row["year_published"],
            original_year=row["original_year"],
            language=row["language"],
            original_language=row["original_language"],
            publisher=row["publisher"],
            page_count=row["page_count"],
            format=row["format"],
            cover_url=row["cover_url"],
            summary=row["summary"],
            reading_status=row["reading_status"],
            date_started=row["date_started"],
            date_read=row["date_read"],
            year_read=row["year_read"],
            reread=row["reread"],
            is_recommended=bool(row["is_recommended"]),
            my_notes=row["my_notes"],
            my_summary=row["my_summary"],
            reading_context=row["reading_context"],
            series_name=row["series_name"],
            series_position=row["series_position"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class ThemeDB:
    """Database operations for themes."""
    
    @staticmethod
    def add(theme: Theme) -> int:
        """Add a new theme. Returns the new theme ID."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO themes (name, slug, description, display_order) VALUES (?, ?, ?, ?)",
                (theme.name, theme.slug, theme.description, theme.display_order)
            )
            conn.commit()
            return cursor.lastrowid
    
    @staticmethod
    def get_all() -> List[Theme]:
        """Get all themes ordered by display_order."""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM themes ORDER BY display_order, name"
            ).fetchall()
            return [Theme(
                id=row["id"],
                name=row["name"],
                slug=row["slug"],
                description=row["description"],
                display_order=row["display_order"]
            ) for row in rows]
    
    @staticmethod
    def get_by_slug(slug: str) -> Optional[Theme]:
        """Get a theme by slug."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM themes WHERE slug = ?", (slug,)
            ).fetchone()
            if row:
                return Theme(
                    id=row["id"],
                    name=row["name"],
                    slug=row["slug"],
                    description=row["description"],
                    display_order=row["display_order"]
                )
        return None
    
    @staticmethod
    def get_with_counts() -> List[dict]:
        """Get all themes with book counts."""
        with get_db() as conn:
            rows = conn.execute("""
                SELECT t.*, COUNT(bt.book_id) as book_count
                FROM themes t
                LEFT JOIN book_themes bt ON t.id = bt.theme_id
                GROUP BY t.id
                ORDER BY t.display_order, t.name
            """).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def delete(theme_id: int) -> None:
        """Delete a theme by ID."""
        with get_db() as conn:
            conn.execute("DELETE FROM themes WHERE id = ?", (theme_id,))
            conn.commit()
