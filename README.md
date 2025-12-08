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

# Initialize database
python scripts/init_db.py
```

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
4. Add custom domain: `books.caseyjr.org`

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
│   ├── books.db              # SQLite database
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
