#!/usr/bin/env python3
"""Remove duplicate books, keeping the one with most metadata."""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from models import BookDB

def score_book(book):
    """Higher score = more metadata."""
    score = 0
    score += len(book.themes) * 10  # Themes are valuable
    score += 5 if book.page_count else 0
    score += 5 if book.cover_url else 0
    score += 3 if book.summary else 0
    score += 2 if book.is_recommended else 0
    return score

def dedupe(dry_run=True):
    books = BookDB.get_all(include_themes=True)
    by_title = defaultdict(list)
    
    for b in books:
        key = b.title.lower().strip()
        by_title[key].append(b)
    
    dupes = {k: v for k, v in by_title.items() if len(v) > 1}
    
    to_delete = []
    
    for title, copies in dupes.items():
        # Score each copy
        scored = [(score_book(b), b) for b in copies]
        scored.sort(key=lambda x: (-x[0], x[1].id))  # Highest score first, then lowest ID
        
        keeper = scored[0][1]
        deletions = [b for _, b in scored[1:]]
        
        print(f"\n{keeper.title}")
        print(f"  KEEP: ID {keeper.id} (score: {scored[0][0]}, themes: {len(keeper.themes)}, pages: {keeper.page_count})")
        for _, b in scored[1:]:
            print(f"  DELETE: ID {b.id} (score: {score_book(b)}, themes: {len(b.themes)}, pages: {b.page_count})")
            to_delete.append(b.id)
    
    print(f"\n{'=' * 40}")
    print(f"Total duplicates to remove: {len(to_delete)}")
    
    if dry_run:
        print("\nDRY RUN - no changes made. Run with --execute to delete.")
    else:
        for book_id in to_delete:
            BookDB.delete(book_id)
        print(f"\nDeleted {len(to_delete)} duplicate books.")

if __name__ == '__main__':
    execute = '--execute' in sys.argv
    dedupe(dry_run=not execute)