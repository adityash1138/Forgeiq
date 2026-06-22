# ForgeIQ

B2B lead-intelligence platform for the Indian manufacturing / EV sector.
It collects signals from 13 data sources, scores companies by purchase intent
across applications, and delivers qualified leads to vendors with exclusivity
windows.

## Architecture

```
Data Collection → Signal Processing → Intelligence Engine → API → Frontend
```

Every scraper writes **only** to `raw_signals`. Everything else is computed
downstream from that single source of truth.

| Layer | Folder | Responsibility |
|-------|--------|----------------|
| Data Collection | `scrapers/` | 13 scrapers, one per signal source |
| Signal Processing | `processing/` | Dedup, app-tagging, entity resolution |
| Intelligence Engine | `engine/` | Scoring, decay, negatives, cascade |
| Contact Intelligence | `contact/` | Contact sourcing + staleness |
| Lead Delivery | `delivery/` | Routing, exclusivity, lead cards |
| Feedback Loop | `feedback/` | Outcome capture |
| API | `api/` | FastAPI REST endpoints |
| Scheduler | `scheduler/` | APScheduler orchestration |
| Database | `db/` | Schema, seed, connection |
| Config | `config/` | Signal / cascade / negative configs |

## Tech stack

PostgreSQL (Supabase) · Python 3.11 · requests + BeautifulSoup ·
Claude API (claude-sonnet-4-6) for entity resolution · FastAPI ·
APScheduler · Railway hosting.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in DATABASE_URL, ANTHROPIC_API_KEY, etc.
python -m db.setup_database   # creates 16 tables + seeds config
```

`python -m db.setup_database` prints a row count for every table and confirms
`signal_type_config` has 13 rows.

## Build sequence

This system is built one testable piece at a time (see the Engineering
Blueprint). Each module ships with an `if __name__ == "__main__"` block so it
can be run and verified in isolation before the next piece begins.

- **Week 1** — Database setup + config seed ✅
- Week 2 — BaseScraper + GeM scraper
- Week 3 — BSE scraper + deduplicator
- … through Week 14 (feedback loop + WhatsApp webhook)
