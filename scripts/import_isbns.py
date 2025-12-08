#!/usr/bin/env python3
"""Import ISBNs from CSV and update books."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import BookDB

def import_isbns(filepath: str):
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    updated = 0
    
    for row in rows:
        # Handle both column names
        isbn = row.get('found_isbn') or row.get('isbn_to_add') or ''
        isbn = isbn.strip()
        if not isbn:
            continue
        
        book_id = int(row['id'])
        book = BookDB.get(book_id)
        
        if not book:
            print(f"Book ID {book_id} not found")
            continue
        
        isbn_clean = isbn.replace('-', '').replace(' ', '')
        
        if len(isbn_clean) == 13:
            book.isbn13 = isbn_clean
        elif len(isbn_clean) == 10:
            book.isbn = isbn_clean
        else:
            book.isbn13 = isbn_clean
        
        BookDB.update(book)
        print(f"Updated: {book.title}")
        updated += 1
    
    print(f"\nUpdated {updated} books with ISBNs")

if __name__ == '__main__':
    filepath = sys.argv[1] if len(sys.argv) > 1 else 'isbn_lookup.csv'
    import_isbns(filepath)