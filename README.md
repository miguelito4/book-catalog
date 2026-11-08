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
python3 -m venv venv
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
python3 scripts/cli.py add --isbn 9780374529253

# Add manually
python3 scripts/cli.py add --title "2666" --author "Roberto Bolaño" --year 2004

# Add with themes
python3 scripts/cli.py add --isbn 9780374529253 --themes "fiction,latin-american-literature"

# Mark as recommended
python3 scripts/cli.py add --isbn 9780374529253 --recommended

# Import from CSV
python3 scripts/cli.py import --file reading-list.csv
```

### Syncing from Reading List

New books come from a [Reading List](https://readinglist.app/) CSV export. Any book finished on or after the sync cutoff (`meta.sync_cutoff`, initially 2026-08-04) that isn't already in the catalog becomes a review batch:

```bash
# Build a review batch from an export (default: newest inbox/*.csv)
python3 scripts/sync_reading_list.py --csv "Reading List - 2026-11-08.csv"
#   -> inbox/pending.json   enriched records (Open Library / Google Books)
#   -> inbox/review.md      review form: every theme as a checkbox, suggestions pre-checked

# Tick themes / ⭐ Recommended / Skip in review.md, then apply
python3 scripts/apply_pending.py
#   -> writes the database, refreshes catalog.json and books.sql, clears inbox/
```

- **Themes** are suggested by Claude when `ANTHROPIC_API_KEY` is set (model: `CLAUDE_MODEL`, default `claude-haiku-5-5`), otherwise by subject keywords. Only existing theme slugs can be suggested or applied.
- **Duplicates:** a book matching an existing entry by ISBN-13 or title+author arrives with *Already in catalog* checked. Applying links the entry (`reading_list_id`, plus a missing finish date) and adds nothing new. Untick it to add the book as new.
- **Skips** are remembered in `sync_skips` and never offered again.
- `date_read` is Reading List's *Finished Reading*; `date_added` is the day the batch was applied.

### Automated flow (GitHub Actions)

1. A Reading List export is pushed to `inbox/` → **Sync from Reading List** opens (or updates) a PR from `sync/reading-list` whose description is the review form. Re-syncs keep any ticks already made.
2. Tick themes and ⭐ in the PR description. Every edit triggers a dry run: a red ✗ means merging would fail (e.g. a book with no theme).
3. **Merge** → **Apply reviewed books** writes the batch, refreshes `books.sql` and `catalog.json`, pushes to `main`, and comments a summary on the PR. Netlify deploys.

To drop a book, tick *Skip* and merge. Closing the PR without merging just means the same books come back next sync. If apply fails after a merge, edit the merged PR's description and re-run *Apply reviewed books* from the Actions tab with the PR number.

### The iOS Shortcut ("Sync Books")

When a book is finished in Reading List, one tap pushes the export to `inbox/reading-list.csv` through GitHub's contents API. That commit triggers the sync above. Build it on a Mac (it syncs to the iPhone through iCloud) and run it from the phone:

| # | Action | Settings |
|---|--------|----------|
| 1 | **Reading List → Export data** | as **CSV** |
| 2 | **Base64 Encode** | input: Export · *Line Breaks:* **None** |
| 3 | **Get Contents of URL** | `https://api.github.com/repos/<owner>/book-catalog/contents/inbox/reading-list.csv` · **GET** · headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json` |
| 4 | **Get Dictionary Value** | `sha` in *Contents of URL*, the current file's ID, required to replace it |
| 5 | **Get Contents of URL** | same URL and headers · **PUT** · JSON body: `message` = `Reading List export`, `content` = *Base64 Encoded*, `sha` = *Dictionary Value*, `branch` = `main` |
| 6 | **Show Result** | success shows `"commit"`; failure shows GitHub's `"message"` |

- **Token:** fine-grained personal access token, only this repo, *Contents: read and write*. Use a separate token from any laptop token so either can be revoked alone.
- **Insert variables** (steps 5's `content` and `sha`) with right-click → *Insert Variable*. They're only offered from actions *above* the current one.
- **Run it manually** (home screen or Siri) rather than as an "app closed" automation. The export changes whenever reading progress does, so an automation would commit on every close even with nothing new to add.

Setup: repo secret `ANTHROPIC_API_KEY`; optional repo variable `CLAUDE_MODEL`; *Settings → Actions → General → Allow GitHub Actions to create and approve pull requests*.

### Managing Themes

```bash
# List themes
python3 scripts/cli.py themes list

# Add theme
python3 scripts/cli.py themes add --name "Latin American Literature" --slug "latin-american-lit"

# Tag a book
python3 scripts/cli.py tag --book-id 1 --theme "latin-american-lit"
```

### Enrichment

```bash
# Enrich all books missing metadata
python3 scripts/enrich.py

# Enrich specific book
python3 scripts/enrich.py --book-id 1

# Force re-enrich (overwrite existing)
python3 scripts/enrich.py --force
```

### Building the Site

```bash
# Export database to JSON
python3 scripts/export.py

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
