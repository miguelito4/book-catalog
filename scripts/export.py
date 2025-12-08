#!/usr/bin/env python3
"""
Export the book catalog database to JSON for the static site generator.

Generates catalog.json in the site/_data directory, which Eleventy
uses to build the static site.

Usage:
    python export.py                    # Export to site/_data/catalog.json
    python export.py --output file.json # Export to custom location
    python export.py --pretty           # Pretty-print JSON
"""

import argparse
import json
from pathlib import Path
from datetime import date, datetime
from typing import Any

from models import BookDB, ThemeDB


# Default output location for Eleventy
DEFAULT_OUTPUT = Path(__file__).parent.parent / "site" / "_data" / "catalog.json"

# Also save a backup in data/export
BACKUP_DIR = Path(__file__).parent.parent / "data" / "export"


def serialize_value(obj: Any) -> Any:
    """Custom JSON serializer for dates and other types."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def export_catalog(output_path: Path, pretty: bool = False) -> None:
    """Export the full catalog to JSON."""
    
    print("Exporting book catalog...")
    
    # Fetch all data
    books = BookDB.get_all(include_themes=True, include_links=True)
    themes = ThemeDB.get_with_counts()
    
    # Build export structure
    catalog = {
        "generated_at": datetime.now().isoformat(),
        "stats": {
            "total_books": len(books),
            "recommended_count": sum(1 for b in books if b.is_recommended),
            "themes_count": len(themes),
        },
        "themes": [
            {
                "slug": t["slug"],
                "name": t["name"],
                "description": t["description"],
                "book_count": t["book_count"],
            }
            for t in themes
            if t["book_count"] > 0  # Only include themes with books
        ],
        "books": [],
    }
    
    # Process books
    for book in books:
        # Only export books with 'read' status by default
        # (You could make this configurable)
        if book.reading_status not in ("read", "reading"):
            continue
        
        book_data = {
            "id": book.id,
            "title": book.title,
            "subtitle": book.subtitle,
            "author": book.author,
            "additional_authors": book.additional_authors,
            "translator": book.translator,
            "year_published": book.year_published,
            "original_year": book.original_year,
            "language": book.language,
            "original_language": book.original_language,
            "publisher": book.publisher,
            "page_count": book.page_count,
            "format": book.format,
            "cover_url": book.cover_url,
            "summary": book.summary,
            "reading_status": book.reading_status,
            "date_read": book.date_read,
            "year_read": book.year_read,
            "is_recommended": book.is_recommended,
            "my_notes": book.my_notes,
            "my_summary": book.my_summary,
            "series_name": book.series_name,
            "series_position": book.series_position,
            "themes": book.themes,
            "links": [
                {
                    "type": link["link_type"],
                    "url": link["url"],
                    "title": link["title"],
                }
                for link in book.links
            ],
        }
        
        # Remove None values to keep JSON clean
        book_data = {k: v for k, v in book_data.items() if v is not None}
        
        catalog["books"].append(book_data)
    
    # Sort books by author, then title
    catalog["books"].sort(key=lambda b: (b.get("author", "").lower(), b.get("title", "").lower()))
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write JSON
    with open(output_path, 'w', encoding='utf-8') as f:
        if pretty:
            json.dump(catalog, f, indent=2, default=serialize_value, ensure_ascii=False)
        else:
            json.dump(catalog, f, default=serialize_value, ensure_ascii=False)
    
    print(f"Exported {len(catalog['books'])} books to {output_path}")
    
    # Save timestamped backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"catalog_{timestamp}.json"
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, default=serialize_value, ensure_ascii=False)
    print(f"Backup saved to {backup_path}")
    
    # Print summary
    print(f"\nCatalog Summary:")
    print(f"  Total books: {catalog['stats']['total_books']}")
    print(f"  Recommended: {catalog['stats']['recommended_count']}")
    print(f"  Themes: {catalog['stats']['themes_count']}")
    
    # Theme breakdown
    print(f"\n  Books by theme:")
    for theme in catalog["themes"]:
        print(f"    {theme['name']}: {theme['book_count']}")


def main():
    parser = argparse.ArgumentParser(description="Export book catalog to JSON")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT, help="Output file path")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()
    
    export_catalog(args.output, pretty=args.pretty)


if __name__ == "__main__":
    main()
