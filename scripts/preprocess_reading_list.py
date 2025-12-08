#!/usr/bin/env python3
"""
Preprocess Reading List export for import into book catalog.
Filters to read books and auto-assigns themes from subjects.
"""

import csv
import re
from pathlib import Path

# Map subject keywords to your theme slugs
THEME_KEYWORDS = {
    'fiction': ['fiction', 'novels', 'short stories', 'literary'],
    'history': ['history', 'ancient', 'medieval', 'modern', '19th century', '20th century'],
    'philosophy': ['philosophy', 'ethics', 'critical theory'],
    'religion': ['religion', 'theology', 'christianity', 'spirituality', 'religious'],
    'politics-economics': ['political science', 'economics', 'politics', 'economic', 'finance'],
    'science-technology': ['science', 'technology', 'engineering', 'biology', 'physics'],
    'biography': ['biography', 'memoir', 'autobiograph'],
    'essays-lectures': ['essays', 'lectures', 'literary collections'],
}

def guess_themes(subjects: str) -> list:
    """Match subject string to theme slugs."""
    if not subjects:
        return []
    
    subjects_lower = subjects.lower()
    matched = []
    
    for theme_slug, keywords in THEME_KEYWORDS.items():
        for keyword in keywords:
            if keyword in subjects_lower:
                matched.append(theme_slug)
                break
    
    return matched

def flip_author_name(author: str) -> str:
    """Convert 'Last, First' to 'First Last'."""
    if not author:
        return ""
    # Handle multiple authors separated by semicolons
    authors = [a.strip() for a in author.split(';')]
    flipped = []
    for a in authors:
        if ',' in a:
            parts = a.split(',', 1)
            flipped.append(f"{parts[1].strip()} {parts[0].strip()}")
        else:
            flipped.append(a)
    return '; '.join(flipped)

def process_reading_list(input_file: Path, output_file: Path):
    """Process Reading List CSV into import-ready format."""
    
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Filter to books with Finished Reading date
    read_books = [r for r in rows if r.get('Finished Reading', '').strip()]
    print(f"Found {len(read_books)} finished books out of {len(rows)} total")
    
    # Prepare output
    output_rows = []
    for row in read_books:
        themes = guess_themes(row.get('Subjects', ''))
        
        output_rows.append({
            'title': row.get('Title', ''),
            'subtitle': row.get('Subtitle', ''),
            'author': flip_author_name(row.get('Authors', '')),
            'isbn13': row.get('ISBN-13', ''),
            'year_published': '',  # Not in source, will enrich later
            'date_read': row.get('Finished Reading', ''),
            'page_count': row.get('Page Count', ''),
            'publisher': row.get('Publisher', ''),
            'summary': row.get('Description', ''),
            'themes': ','.join(themes),
            'notes': row.get('Notes', ''),
        })
    
    # Write output
    fieldnames = ['title', 'subtitle', 'author', 'isbn13', 'year_published', 
                  'date_read', 'page_count', 'publisher', 'summary', 'themes', 'notes']
    
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)
    
    print(f"Wrote {len(output_rows)} books to {output_file}")
    
    # Theme summary
    from collections import Counter
    all_themes = []
    for row in output_rows:
        all_themes.extend(row['themes'].split(','))
    theme_counts = Counter(t for t in all_themes if t)
    print("\nTheme distribution:")
    for theme, count in theme_counts.most_common():
        print(f"  {theme}: {count}")

if __name__ == '__main__':
    import sys
    input_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('reading_list.csv')
    output_file = Path('books_to_import.csv')
    process_reading_list(input_file, output_file)