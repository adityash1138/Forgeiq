"""Signal deduplication.

Runs immediately after each scraper deposits rows (and is also enforced at
intake by BaseScraper.is_duplicate). Suppresses exact duplicates — same company
+ same signal_type within a 7-day window + same source_url — before they
corrupt scores.

BaseScraper already blocks duplicates on write. This module provides:
  - is_duplicate(): the canonical check, reused by the base scraper
  - sweep_duplicates(): a safety net that finds and removes any duplicate rows
    that slipped in (e.g. two scrapers writing the same announcement).
"""
from __future__ import annotations

from datetime import date

from db.connection import fetch_all, fetch_one, get_cursor


def is_duplicate(raw_company_name: str, signal_type: str,
                 date_detected: date, source_url: str) -> bool:
    """True if a matching signal exists within 7 days before date_detected."""
    row = fetch_one(
        """
        SELECT 1 FROM raw_signals
        WHERE raw_company_name ILIKE %s
          AND signal_type = %s
          AND source_url = %s
          AND date_detected >= (%s::date - INTERVAL '7 days')
          AND date_detected <= %s::date
        LIMIT 1
        """,
        (raw_company_name or "", signal_type, source_url or "",
         date_detected, date_detected),
    )
    return row is not None


def sweep_duplicates() -> int:
    """Remove duplicate raw_signals, keeping the earliest of each group.

    A group is (raw_company_name, signal_type, source_url) within the same ISO
    week. Returns the number of rows deleted. Idempotent.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            DELETE FROM raw_signals a
            USING raw_signals b
            WHERE a.id <> b.id
              AND a.raw_company_name IS NOT DISTINCT FROM b.raw_company_name
              AND a.signal_type = b.signal_type
              AND a.source_url IS NOT DISTINCT FROM b.source_url
              AND date_trunc('week', a.date_detected) = date_trunc('week', b.date_detected)
              AND a.created_at > b.created_at
            """
        )
        deleted = cur.rowcount
    print(f"deduplicator.sweep_duplicates: removed {deleted} duplicate rows.")
    return deleted


def process_new_signals() -> int:
    """Pipeline entry point — sweep any duplicates that slipped past intake."""
    return sweep_duplicates()


if __name__ == "__main__":
    # Offline smoke: confirm the module imports and the query strings are valid
    # Python. Full behaviour is verified against a live DB in Week 3's test:
    # run BseScraper twice and confirm no new duplicate rows on the second run.
    print("deduplicator loaded. Live test: run a scraper twice, then")
    print("SELECT raw_company_name, COUNT(*) FROM raw_signals "
          "GROUP BY 1 HAVING COUNT(*) > 1; should return 0 rows.")
