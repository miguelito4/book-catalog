#!/usr/bin/env python3
"""
Command-line interface for managing the book catalog.

Usage:
    python cli.py add --isbn 9780374529253
    python cli.py add --title "2666" --author "Roberto Bolaño"
    python cli.py import --file reading-list.csv
    python cli.py list
    python cli.py show 1
    python cli.py themes list
    python cli.py themes add --name "Climate Technology" --slug "climate-tech"
    python cli.py tag --book-id 1 --theme fiction
"""

import argparse
import csv
import sys
import re
from pathlib import Path
from datetime import date

from models import Book, Theme, BookDB, ThemeDB, DB_PATH


def normalize_isbn(isbn: str) -> tuple[str, str]:
    """
    Normalize an ISBN, returning (isbn10, isbn13) tuple.
    Strips hyphens and validates format.
    """
    isbn = re.sub(r'[^0-9X]', '', isbn.upper())
    
    if len(isbn) == 10:
        return isbn, None
    elif len(isbn) == 13:
        return None, isbn
    else:
        return isbn, isbn  # Store as-is if weird format


def add_book(args):
    """Add a new book to the catalog."""
    
    # Check if book already exists
    if args.isbn:
        existing = BookDB.get_by_isbn(args.isbn)
        if existing:
            print(f"Book already exists with ID {existing.id}: {existing.title}")
            return
    
    isbn, isbn13 = (None, None)
    if args.isbn:
        isbn, isbn13 = normalize_isbn(args.isbn)
    
    book = Book(
        isbn=isbn,
        isbn13=isbn13,
        title=args.title or "Unknown Title",
        author=args.author,
        translator=args.translator,
        year_published=args.year,
        year_read=args.year_read or (date.today().year if not args.date_read else None),
        date_read=args.date_read,
        reading_status=args.status or "read",
        is_recommended=args.recommended or False,
        my_notes=args.notes,
        format=args.format,
    )
    
    book_id = BookDB.add(book)
    print(f"Added book with ID {book_id}: {book.title}")
    
    # Add themes if specified
    if args.themes:
        theme_slugs = [t.strip() for t in args.themes.split(",")]
        for slug in theme_slugs:
            try:
                BookDB.add_theme(book_id, slug)
                print(f"  Tagged with: {slug}")
            except ValueError as e:
                print(f"  Warning: {e}")
    
    # Suggest enrichment
    if isbn or isbn13 or (book.title and book.author):
        print(f"\nRun 'python scripts/enrich.py' to fetch covers and summaries")


def import_csv(args):
    """Import books from a CSV file."""
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    
    # Detect file format and map columns
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        
        # Column mappings for common formats
        # Goodreads export
        if 'Book Id' in headers:
            column_map = {
                'title': 'Title',
                'author': 'Author',
                'isbn': 'ISBN',
                'isbn13': 'ISBN13',
                'year_published': 'Original Publication Year',
                'date_read': 'Date Read',
                'my_notes': 'My Review',
                'page_count': 'Number of Pages',
            }
            is_goodreads = True
        # StoryGraph export
        elif 'Title' in headers and 'Authors' in headers:
            column_map = {
                'title': 'Title',
                'author': 'Authors',
                'isbn': 'ISBN/UID',
                'date_read': 'Last Date Read',
            }
            is_goodreads = False
        # Generic/custom format
        else:
            column_map = {
                'title': 'title',
                'author': 'author',
                'isbn': 'isbn',
                'isbn13': 'isbn13',
                'year_published': 'year_published',
                'date_read': 'date_read',
                'year_read': 'year_read',
                'my_notes': 'notes',
                'is_recommended': 'recommended',
                'themes': 'themes',
            }
            is_goodreads = False
        
        # Reset reader
        f.seek(0)
        reader = csv.DictReader(f)
        
        added = 0
        skipped = 0
        
        for row in reader:
            # Extract values using column map
            def get_val(key):
                col = column_map.get(key)
                if col and col in row:
                    val = row[col].strip() if row[col] else None
                    # Handle Goodreads's weird ISBN format
                    if key in ('isbn', 'isbn13') and val:
                        val = val.replace('="', '').replace('"', '')
                    return val if val else None
                return None
            
            title = get_val('title')
            if not title:
                continue
            
            isbn = get_val('isbn')
            isbn13 = get_val('isbn13')
            
            # Check for duplicates
            if isbn and BookDB.get_by_isbn(isbn):
                print(f"Skipping duplicate: {title}")
                skipped += 1
                continue
            if isbn13 and BookDB.get_by_isbn(isbn13):
                print(f"Skipping duplicate: {title}")
                skipped += 1
                continue
            
            # Parse year
            year_published = None
            year_str = get_val('year_published')
            if year_str:
                try:
                    year_published = int(float(year_str))
                except (ValueError, TypeError):
                    pass
            
            # Parse date read
            date_read = get_val('date_read')
            year_read = None
            if date_read:
                # Try to extract year from date
                try:
                    if '/' in date_read:
                        year_read = int(date_read.split('/')[-1])
                    elif '-' in date_read:
                        year_read = int(date_read.split('-')[0])
                except (ValueError, IndexError):
                    pass
            
            # Parse year_read directly if provided
            if not year_read:
                yr = get_val('year_read')
                if yr:
                    try:
                        year_read = int(yr)
                    except ValueError:
                        pass
            
            # Parse recommended
            is_recommended = False
            rec = get_val('is_recommended')
            if rec:
                is_recommended = rec.lower() in ('true', 'yes', '1', 'x')
            
            # Parse page count
            page_count = None
            pc = get_val('page_count')
            if pc:
                try:
                    page_count = int(pc)
                except ValueError:
                    pass
            
            book = Book(
                isbn=isbn,
                isbn13=isbn13,
                title=title,
                author=get_val('author'),
                year_published=year_published,
                date_read=date_read if date_read and '-' in date_read else None,
                year_read=year_read,
                my_notes=get_val('my_notes'),
                page_count=page_count,
                is_recommended=is_recommended,
                reading_status='read',
            )
            
            book_id = BookDB.add(book)
            print(f"Added: {title} (ID: {book_id})")
            added += 1
            
            # Add themes if provided
            themes = get_val('themes')
            if themes:
                for slug in themes.split(','):
                    slug = slug.strip()
                    try:
                        BookDB.add_theme(book_id, slug)
                    except ValueError:
                        pass
        
        print(f"\nImport complete: {added} added, {skipped} skipped")
        if added > 0:
            print("Run 'python enrich.py' to fetch metadata for new books")


def list_books(args):
    """List all books in the catalog."""
    books = BookDB.get_all(include_themes=True)
    
    if not books:
        print("No books in catalog. Add some with 'python cli.py add'")
        return
    
    # Filter by status if specified
    if args.status:
        books = [b for b in books if b.reading_status == args.status]
    
    # Filter by theme if specified
    if args.theme:
        books = [b for b in books if args.theme in b.themes]
    
    # Filter recommended only
    if args.recommended:
        books = [b for b in books if b.is_recommended]
    
    print(f"\n{'ID':<5} {'Title':<40} {'Author':<25} {'Year':<6} {'Rec':<4} Themes")
    print("-" * 100)
    
    for book in books:
        rec = "★" if book.is_recommended else ""
        year = book.year_read or book.year_published or ""
        themes = ", ".join(book.themes) if book.themes else ""
        title = book.title[:38] + ".." if len(book.title) > 40 else book.title
        author = (book.author or "")[:23] + ".." if len(book.author or "") > 25 else (book.author or "")
        
        print(f"{book.id:<5} {title:<40} {author:<25} {year:<6} {rec:<4} {themes}")
    
    print(f"\nTotal: {len(books)} books")


def show_book(args):
    """Show details for a specific book."""
    book = BookDB.get(args.book_id)
    
    if not book:
        print(f"Book not found: {args.book_id}")
        sys.exit(1)
    
    book.themes = BookDB.get_themes(book.id)
    book.links = BookDB.get_links(book.id)
    
    print(f"\n{'='*60}")
    print(f"ID: {book.id}")
    print(f"Title: {book.title}")
    if book.subtitle:
        print(f"Subtitle: {book.subtitle}")
    print(f"Author: {book.author or 'Unknown'}")
    if book.translator:
        print(f"Translator: {book.translator}")
    if book.year_published:
        print(f"Published: {book.year_published}")
    if book.isbn:
        print(f"ISBN: {book.isbn}")
    if book.isbn13:
        print(f"ISBN-13: {book.isbn13}")
    print(f"\nStatus: {book.reading_status}")
    if book.date_read:
        print(f"Date Read: {book.date_read}")
    elif book.year_read:
        print(f"Year Read: {book.year_read}")
    print(f"Recommended: {'Yes' if book.is_recommended else 'No'}")
    
    if book.themes:
        print(f"\nThemes: {', '.join(book.themes)}")
    
    if book.summary:
        print(f"\nSummary:\n{book.summary[:500]}...")
    
    if book.my_notes:
        print(f"\nNotes:\n{book.my_notes}")
    
    if book.cover_url:
        print(f"\nCover: {book.cover_url}")
    
    if book.links:
        print(f"\nLinks:")
        for link in book.links:
            print(f"  [{link['link_type']}] {link['title'] or link['url']}")
    
    print(f"{'='*60}\n")


def edit_book(args):
    """Edit an existing book."""
    book = BookDB.get(args.book_id)
    
    if not book:
        print(f"Book not found: {args.book_id}")
        sys.exit(1)
    
    # Update fields if provided
    if args.title:
        book.title = args.title
    if args.author:
        book.author = args.author
    if args.translator:
        book.translator = args.translator
    if args.year:
        book.year_published = args.year
    if args.year_read:
        book.year_read = args.year_read
    if args.notes:
        book.my_notes = args.notes
    if args.status:
        book.reading_status = args.status
    if args.recommended is not None:
        book.is_recommended = args.recommended
    
    BookDB.update(book)
    print(f"Updated book {book.id}: {book.title}")


def delete_book(args):
    """Delete a book from the catalog."""
    book = BookDB.get(args.book_id)
    
    if not book:
        print(f"Book not found: {args.book_id}")
        sys.exit(1)
    
    if not args.force:
        confirm = input(f"Delete '{book.title}'? [y/N] ")
        if confirm.lower() != 'y':
            print("Cancelled")
            return
    
    BookDB.delete(args.book_id)
    print(f"Deleted: {book.title}")


def manage_themes(args):
    """Manage themes (list, add, delete)."""
    if args.theme_action == 'list':
        themes = ThemeDB.get_with_counts()
        if not themes:
            print("No themes defined.")
            return
        
        print(f"\n{'Slug':<25} {'Name':<30} {'Books':<6}")
        print("-" * 65)
        for t in themes:
            print(f"{t['slug']:<25} {t['name']:<30} {t['book_count']:<6}")
    
    elif args.theme_action == 'add':
        if not args.name or not args.slug:
            print("Error: --name and --slug required")
            sys.exit(1)
        
        # Validate slug format
        slug = args.slug.lower().replace(' ', '-')
        slug = re.sub(r'[^a-z0-9-]', '', slug)
        
        theme = Theme(
            name=args.name,
            slug=slug,
            description=args.description,
        )
        
        try:
            theme_id = ThemeDB.add(theme)
            print(f"Added theme '{args.name}' with slug '{slug}'")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif args.theme_action == 'delete':
        if not args.slug:
            print("Error: --slug required")
            sys.exit(1)
        
        theme = ThemeDB.get_by_slug(args.slug)
        if not theme:
            print(f"Theme not found: {args.slug}")
            sys.exit(1)
        
        ThemeDB.delete(theme.id)
        print(f"Deleted theme: {args.slug}")


def tag_book(args):
    """Add or remove theme from a book."""
    book = BookDB.get(args.book_id)
    if not book:
        print(f"Book not found: {args.book_id}")
        sys.exit(1)
    
    if args.remove:
        BookDB.remove_theme(args.book_id, args.theme)
        print(f"Removed '{args.theme}' from '{book.title}'")
    else:
        try:
            BookDB.add_theme(args.book_id, args.theme)
            print(f"Tagged '{book.title}' with '{args.theme}'")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)


def add_link(args):
    """Add a link to a book."""
    book = BookDB.get(args.book_id)
    if not book:
        print(f"Book not found: {args.book_id}")
        sys.exit(1)
    
    link_id = BookDB.add_link(
        args.book_id,
        args.type,
        args.url,
        args.title,
        args.notes
    )
    print(f"Added link to '{book.title}'")


def main():
    parser = argparse.ArgumentParser(
        description="Manage your personal book catalog",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new book')
    add_parser.add_argument('--isbn', help='ISBN (10 or 13 digit)')
    add_parser.add_argument('--title', help='Book title')
    add_parser.add_argument('--author', help='Author name')
    add_parser.add_argument('--translator', help='Translator name')
    add_parser.add_argument('--year', type=int, help='Year published')
    add_parser.add_argument('--year-read', type=int, help='Year you read it')
    add_parser.add_argument('--date-read', help='Date read (YYYY-MM-DD)')
    add_parser.add_argument('--status', choices=['read', 'reading', 'want-to-read', 'abandoned'], default='read')
    add_parser.add_argument('--recommended', action='store_true', help='Mark as recommended')
    add_parser.add_argument('--themes', help='Comma-separated theme slugs')
    add_parser.add_argument('--notes', help='Your notes')
    add_parser.add_argument('--format', choices=['physical', 'ebook', 'audiobook'])
    add_parser.set_defaults(func=add_book)
    
    # Import command
    import_parser = subparsers.add_parser('import', help='Import from CSV')
    import_parser.add_argument('--file', '-f', required=True, help='CSV file to import')
    import_parser.set_defaults(func=import_csv)
    
    # List command
    list_parser = subparsers.add_parser('list', help='List books')
    list_parser.add_argument('--status', choices=['read', 'reading', 'want-to-read', 'abandoned'])
    list_parser.add_argument('--theme', help='Filter by theme slug')
    list_parser.add_argument('--recommended', action='store_true', help='Show only recommended')
    list_parser.set_defaults(func=list_books)
    
    # Show command
    show_parser = subparsers.add_parser('show', help='Show book details')
    show_parser.add_argument('book_id', type=int, help='Book ID')
    show_parser.set_defaults(func=show_book)
    
    # Edit command
    edit_parser = subparsers.add_parser('edit', help='Edit a book')
    edit_parser.add_argument('book_id', type=int, help='Book ID')
    edit_parser.add_argument('--title', help='New title')
    edit_parser.add_argument('--author', help='New author')
    edit_parser.add_argument('--translator', help='Translator')
    edit_parser.add_argument('--year', type=int, help='Year published')
    edit_parser.add_argument('--year-read', type=int, help='Year read')
    edit_parser.add_argument('--notes', help='Your notes')
    edit_parser.add_argument('--status', choices=['read', 'reading', 'want-to-read', 'abandoned'])
    edit_parser.add_argument('--recommended', action='store_true', dest='recommended')
    edit_parser.add_argument('--not-recommended', action='store_false', dest='recommended')
    edit_parser.set_defaults(func=edit_book, recommended=None)
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a book')
    delete_parser.add_argument('book_id', type=int, help='Book ID')
    delete_parser.add_argument('--force', '-f', action='store_true', help='Skip confirmation')
    delete_parser.set_defaults(func=delete_book)
    
    # Themes command
    themes_parser = subparsers.add_parser('themes', help='Manage themes')
    themes_parser.add_argument('theme_action', choices=['list', 'add', 'delete'])
    themes_parser.add_argument('--name', help='Theme name')
    themes_parser.add_argument('--slug', help='Theme slug (URL-safe)')
    themes_parser.add_argument('--description', help='Theme description')
    themes_parser.set_defaults(func=manage_themes)
    
    # Tag command
    tag_parser = subparsers.add_parser('tag', help='Tag a book with a theme')
    tag_parser.add_argument('--book-id', type=int, required=True)
    tag_parser.add_argument('--theme', required=True, help='Theme slug')
    tag_parser.add_argument('--remove', action='store_true', help='Remove instead of add')
    tag_parser.set_defaults(func=tag_book)
    
    # Link command
    link_parser = subparsers.add_parser('link', help='Add a link to a book')
    link_parser.add_argument('--book-id', type=int, required=True)
    link_parser.add_argument('--type', required=True, choices=['internal', 'external', 'purchase', 'review', 'author'])
    link_parser.add_argument('--url', required=True)
    link_parser.add_argument('--title', help='Link title')
    link_parser.add_argument('--notes', help='Notes about this link')
    link_parser.set_defaults(func=add_link)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Check database exists
    if not DB_PATH.exists() and args.command != 'init':
        print(f"Database not found. Run 'python init_db.py' first.")
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
