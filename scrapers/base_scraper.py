"""BaseScraper — shared base class every ForgeIQ scraper inherits from.

Enforces consistent behaviour across all 13 sources:
  - signal_id generation (SIG-<timestamp>-<random>)
  - deduplication (same company + signal_type + source_url within 7 days)
  - writing to raw_signals (the single source of truth)
  - triggering entity resolution + score recalculation downstream

Subclasses implement run(), collect raw records, and call write_signal() for
each one. They never touch the database directly.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime

from db.connection import fetch_one, get_cursor

# Cascade trigger signal types — used downstream, defined once here so scrapers
# and the cascade engine agree.
CASCADE_TRIGGER_TYPES = {
    "CAPEX_FILING", "PLI_APPROVAL", "ICEGATE_IMPORT",
    "LAND_ACQUISITION", "EC_CLEARANCE",
}


class BaseScraper:
    def __init__(self, signal_type: str, industry_id: str):
        self.signal_type = signal_type
        self.industry_id = industry_id

    # ------------------------------------------------------------------ utils
    def generate_signal_id(self) -> str:
        """SIG- + compact timestamp + 4-char random suffix (collision-safe)."""
        ts = datetime.now().strftime("%y%m%d%H%M%S")
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"SIG-{ts}-{suffix}"

    def is_duplicate(self, raw_company_name: str, source_url: str) -> bool:
        """True if the same company + signal_type + source_url was seen this week.

        Mirrors processing/deduplicator.py but runs at intake so duplicates are
        never written in the first place.
        """
        row = fetch_one(
            """
            SELECT 1 FROM raw_signals
            WHERE raw_company_name ILIKE %s
              AND signal_type = %s
              AND source_url = %s
              AND date_detected >= (CURRENT_DATE - INTERVAL '7 days')
            LIMIT 1
            """,
            (raw_company_name or "", self.signal_type, source_url or ""),
        )
        return row is not None

    # ------------------------------------------------------------------ write
    def write_signal(self, data: dict) -> str | None:
        """Insert one row into raw_signals. Skips duplicates.

        Expected keys in `data` (all optional except raw_company_name):
            raw_company_name, source, source_url, raw_text_snippet,
            date_detected (date | str, defaults today)

        Returns the new row's UUID, or None if suppressed as a duplicate.
        """
        raw_company_name = data.get("raw_company_name", "")
        source_url = data.get("source_url", "")

        if self.is_duplicate(raw_company_name, source_url):
            return None

        detected = data.get("date_detected") or date.today()
        signal_id = self.generate_signal_id()

        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raw_signals
                  (signal_id, industry_id, date_detected, signal_type,
                   raw_company_name, source, source_url, raw_text_snippet)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    signal_id, self.industry_id, detected, self.signal_type,
                    raw_company_name, data.get("source"), source_url,
                    data.get("raw_text_snippet"),
                ),
            )
            new_id = cur.fetchone()["id"]

        self._trigger_downstream(str(new_id))
        return str(new_id)

    def _trigger_downstream(self, signal_row_id: str) -> None:
        """Kick off entity resolution after a new signal is written.

        Entity resolution (and, once resolved, score recalculation) runs in the
        daily pipeline. We import lazily so the scraper layer has no hard
        dependency on the processing layer being importable in every context
        (e.g. unit tests with a stubbed DB).
        """
        try:
            from processing.entity_resolver import resolve_signal
            resolve_signal(signal_row_id)
        except Exception:
            # Resolution failures must never break ingestion. The daily queue
            # pass will pick this signal up by its null resolved_company_id.
            pass

    # ------------------------------------------------------------------ run
    def run(self):
        raise NotImplementedError("Each scraper must implement run()")
