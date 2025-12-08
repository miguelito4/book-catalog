#!/usr/bin/env python3
"""
Import theme and recommendation changes from books_review.csv
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import BookDB, ThemeDB, get_db

def import_reviews(filepath: str):
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    valid_themes = {t.slug for t in ThemeDB.get_all()}
    
    theme_changes = 0
    rec_changes = 0
    errors = []
    
    for row in rows:
        book_id = int(row['id'])
        book = BookDB.get(book_id)
        
        if not book:
            errors.append(f"Book ID {book_id} not found")
            continue
        
        # Handle themes
        new_themes_str = row.get('new_themes', '').strip()
        if new_themes_str:
            new_themes = [t.strip() for t in new_themes_str.split(',') if t.strip()]
            
            invalid = [t for t in new_themes if t not in valid_themes]
            if invalid:
                errors.append(f"Book {book_id} '{book.title}': invalid themes {invalid}")
                continue
            
            current_themes = set(BookDB.get_themes(book_id))
            new_themes_set = set(new_themes)
            
            for theme in current_themes - new_themes_set:
                BookDB.remove_theme(book_id, theme)
            
            for theme in new_themes_set - current_themes:
                BookDB.add_theme(book_id, theme)
            
            if current_themes != new_themes_set:
                theme_changes += 1
                print(f"Themes updated: {book.title}")
        
        # Handle recommended
        rec_value = row.get('recommended', '').strip().lower()
        is_rec = rec_value in ('x', 'yes', '1', 'true')
        
        if is_rec != book.is_recommended:
            book.is_recommended = is_rec
            BookDB.update(book)
            rec_changes += 1
            status = "recommended" if is_rec else "unmarked"
            print(f"Recommendation {status}: {book.title}")
    
    print(f"\nComplete: {theme_changes} theme changes, {rec_changes} recommendation changes")
    
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  {e}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_reviews.py books_review.csv")
        sys.exit(1)
    
    import_reviews(sys.argv[1])