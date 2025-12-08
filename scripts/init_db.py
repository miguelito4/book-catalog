#!/usr/bin/env python3
"""
Initialize the SQLite database with the book catalog schema.

Run once to create the database, or with --reset to start fresh.
"""

import sqlite3
import os
import argparse
from pathlib import Path

# Database location
DB_PATH = Path(__file__).parent.parent / "data" / "books.db"

SCHEMA = """
-- Core book record
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    
    -- Identifiers (all optional)
    isbn TEXT,
    isbn13 TEXT,
    openlibrary_key TEXT,
    
    -- Core metadata
    title TEXT NOT NULL,
    subtitle TEXT,
    author TEXT,
    additional_authors TEXT,
    translator TEXT,
    year_published INTEGER,
    original_year INTEGER,
    language TEXT,
    original_language TEXT,
    
    -- Edition details
    publisher TEXT,
    page_count INTEGER,
    format TEXT,                    -- 'physical', 'ebook', 'audiobook'
    
    -- Enriched metadata (from APIs)
    cover_url TEXT,
    summary TEXT,
    
    -- Your reading record
    reading_status TEXT DEFAULT 'read',  -- 'read', 'reading', 'want-to-read', 'abandoned'
    date_started DATE,
    date_read DATE,
    year_read INTEGER,              -- Fallback when exact date unknown
    reread INTEGER DEFAULT 0,
    
    -- Your assessment
    is_recommended BOOLEAN DEFAULT 0,
    my_notes TEXT,
    my_summary TEXT,
    reading_context TEXT,
    
    -- Series tracking
    series_name TEXT,
    series_position REAL,
    
    -- Housekeeping
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Themes/topics (curated categories)
CREATE TABLE IF NOT EXISTS themes (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT,
    display_order INTEGER
);

-- Many-to-many: books <-> themes
CREATE TABLE IF NOT EXISTS book_themes (
    book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
    theme_id INTEGER REFERENCES themes(id) ON DELETE CASCADE,
    PRIMARY KEY (book_id, theme_id)
);

-- Flexible links (internal, external, purchase, etc.)
CREATE TABLE IF NOT EXISTS book_links (
    id INTEGER PRIMARY KEY,
    book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL,        -- 'internal', 'external', 'purchase', 'review', 'author'
    url TEXT NOT NULL,
    title TEXT,
    notes TEXT
);

-- Related books (curated connections)
CREATE TABLE IF NOT EXISTS related_books (
    book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
    related_book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
    relationship_type TEXT,         -- 'similar', 'companion', 'response_to', 'influenced_by'
    notes TEXT,
    PRIMARY KEY (book_id, related_book_id)
);

-- Quotes/passages
CREATE TABLE IF NOT EXISTS book_quotes (
    id INTEGER PRIMARY KEY,
    book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
    quote_text TEXT NOT NULL,
    page_number TEXT,               -- TEXT for "Kindle loc 1234" etc.
    chapter TEXT,
    my_note TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_books_reading_status ON books(reading_status);
CREATE INDEX IF NOT EXISTS idx_books_is_recommended ON books(is_recommended);
CREATE INDEX IF NOT EXISTS idx_books_year_read ON books(year_read);
CREATE INDEX IF NOT EXISTS idx_books_author ON books(author);
CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn);
CREATE INDEX IF NOT EXISTS idx_books_isbn13 ON books(isbn13);

-- Trigger to update timestamp on modification
CREATE TRIGGER IF NOT EXISTS update_book_timestamp 
    AFTER UPDATE ON books
    BEGIN
        UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;
"""

# Default themes to get started
DEFAULT_THEMES = [
    ("Fiction", "fiction", "Novels and short stories", 1),
    ("History", "history", "Historical works and historiography", 2),
    ("Philosophy", "philosophy", "Philosophy, ethics, critical theory", 3),
    ("Religion", "religion", "Theology, spirituality, religious texts", 4),
    ("Politics & Economics", "politics-economics", "Political theory, economics, finance, markets", 5),
    ("Science & Technology", "science-technology", "Science writing, technology, engineering", 6),
    ("Biography & Memoir", "biography", "Lives and autobiographies", 7),
    ("Essays & Lectures", "essays-lectures", "Essay and lecture collections", 8),
    ("Poetry", "poetry", "Poetry collections", 9),
    ("Travel", "travel", "Travel writing", 10),
]


def init_database(reset: bool = False) -> None:
    """Initialize the database with schema and default data."""
    
    # Ensure data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    if reset and DB_PATH.exists():
        print(f"Removing existing database: {DB_PATH}")
        os.remove(DB_PATH)
    
    print(f"Initializing database: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Create schema
    cursor.executescript(SCHEMA)
    print("Schema created.")
    
    # Add default themes if themes table is empty
    cursor.execute("SELECT COUNT(*) FROM themes")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO themes (name, slug, description, display_order) VALUES (?, ?, ?, ?)",
            DEFAULT_THEMES
        )
        print(f"Added {len(DEFAULT_THEMES)} default themes.")
    
    conn.commit()
    conn.close()
    
    print("Database initialized successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize the book catalog database")
    parser.add_argument("--reset", action="store_true", help="Delete existing database and start fresh")
    args = parser.parse_args()
    
    init_database(reset=args.reset)
