# Personal Book Catalog

A personal book catalog system with automated enrichment and a static web interface.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  DATA LAYER                                                     │
│  (Python + SQLite)                                              │
│                                                                 │
│  csv import ──┐                                                 │
│               │                                                 │
│  cli.py ──────┼──► books.db ──► enrich.py ──► export.py         │
│               │                                    │            │
│  manual edit ─┘                                    ▼            │
│                                             catalog.json        │
├─────────────────────────────────────────────────────────────────┤
│  BUILD LAYER                                                    │
│  (Eleventy)                                                     │
│                                                                 │
│  catalog.json ──► templates ──► static HTML/CSS/JS              │
├─────────────────────────────────────────────────────────────────┤
│  PRESENTATION LAYER                                             │
│  (Netlify/Cloudflare)                                           │
│                                                                 │
│  books.caseyjr.org ◄── deployed from site/_site/                │
└─────────────────────────────────────────────────────────────────┘
```

## Setup

### Prerequisites

- Python 3.9+
- Node.js 18+

### Installation

```bash
# Clone and enter directory
cd book-catalog

# Python dependencies
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Node dependencies
npm install

# Build the local database from the committed dump
npm run db:load
```

## Data: `books.sql` is the source of truth

`data/books.db` is gitignored. The database lives in git as a plain-text SQL dump, `data/books.sql` (one `INSERT` per row), so every catalog change is a readable diff and the repo doubles as the backup.

- After cloning or pulling: `npm run db:load` (add `-- --force` to replace an existing `books.db`)
- After changing the database (CLI add/edit/tag): `npm run export`, which writes `catalog.json` **and** refreshes `books.sql`. Commit both.
- CI rebuilds the database from `books.sql`, checks the dump round-trips byte for byte, checks that `catalog.json` matches the database, and builds the site.

## Usage

### Adding Books

```bash
# Add by ISBN (metadata auto-fetched)
python scripts/cli.py add --isbn 9780374529253

# Add manually
python scripts/cli.py add --title "2666" --author "Roberto Bolaño" --year 2004

# Add with themes
python scripts/cli.py add --isbn 9780374529253 --themes "fiction,latin-american-literature"

# Mark as recommended
python scripts/cli.py add --isbn 9780374529253 --recommended

# Import from CSV
python scripts/cli.py import --file reading-list.csv
```

### Syncing from Reading List

New books come from a [Reading List](https://readinglist.app/) CSV export. Any book finished on or after the sync cutoff (`meta.sync_cutoff`, initially 2026-08-04) that isn't already in the catalog becomes a review batch:

```bash
# Build a review batch from an export (default: newest inbox/*.csv)
python scripts/sync_reading_list.py --csv "Reading List - 2026-11-08.csv"
#   -> inbox/pending.json   enriched records (Open Library / Google Books)
#   -> inbox/review.md      review form: every theme as a checkbox, suggestions pre-checked

# Tick themes / ⭐ Recommended / Skip in review.md, then apply
python scripts/apply_pending.py
#   -> writes the database, refreshes catalog.json and books.sql, clears inbox/
```

- **Themes** are suggested by Claude when `ANTHROPIC_API_KEY` is set (model: `CLAUDE_MODEL`, default `claude-haiku-5-5`), otherwise by subject keywords. Only existing theme slugs can be suggested or applied.
- **Duplicates:** a book matching an existing entry by ISBN-13 or title+author arrives with *Already in catalog* checked. Applying links the entry (`reading_list_id`, plus a missing finish date) and adds nothing new. Untick it to add the book as new.
- **Skips** are remembered in `sync_skips` and never offered again.
- `date_read` is Reading List's *Finished Reading*; `date_added` is the day the batch was applied.

In the automated flow (#1) the review form is the PR description and the merge applies it.

### Managing Themes

```bash
# List themes
python scripts/cli.py themes list

# Add theme
python scripts/cli.py themes add --name "Latin American Literature" --slug "latin-american-lit"

# Tag a book
python scripts/cli.py tag --book-id 1 --theme "latin-american-lit"
```

### Enrichment

```bash
# Enrich all books missing metadata
python scripts/enrich.py

# Enrich specific book
python scripts/enrich.py --book-id 1

# Force re-enrich (overwrite existing)
python scripts/enrich.py --force
```

### Building the Site

```bash
# Export database to JSON
python scripts/export.py

# Build static site
npm run build

# Preview locally
npm run serve
```

### Full Rebuild

```bash
# One command to export + build
npm run rebuild
```

## Deployment

### Netlify

1. Connect your GitHub repo to Netlify
2. Build command: `npm run rebuild`
3. Publish directory: `site/_site`
4. Add custom domain: `YOUR DOMAIN`

### Manual Deploy

```bash
# Build and deploy
npm run rebuild
# Then upload site/_site/ to your host
```

## CSV Import Format

The importer accepts CSVs with these columns (all optional except title):

```csv
title,author,isbn,year_published,date_read,themes,recommended,notes
"2666","Roberto Bolaño",9780374529253,2004,2023-06-15,"fiction,latin-american-lit",true,"Sprawling masterpiece"
```

Goodreads exports work with some column mapping (handled automatically).

## File Structure

```
book-catalog/
├── data/
│   ├── books.sql             # Committed source of truth (text dump)
│   ├── books.db              # Local SQLite build (gitignored)
│   └── export/               # Backup exports
├── scripts/
│   ├── cli.py                # Command-line interface
│   ├── enrich.py             # API enrichment
│   ├── export.py             # DB → JSON for site
│   ├── init_db.py            # Database initialization
│   └── models.py             # Shared database utilities
├── site/
│   ├── _data/
│   │   └── catalog.json      # Generated from export.py
│   ├── _includes/
│   │   ├── base.njk          # Base template
│   │   ├── book-card.njk     # Book card component
│   │   └── header.njk        # Site header
│   ├── css/
│   │   └── style.css         # Site styles
│   ├── index.njk             # Homepage
│   └── book.njk              # Individual book page template
├── .eleventy.js              # Eleventy configuration
├── package.json              # Node dependencies
├── requirements.txt          # Python dependencies
└── README.md
```

## License

Personal project. Code is MIT licensed.
