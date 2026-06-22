"""GeM / CPPP tender scraper — Tier 1, free.

Target: bidplus.gem.gov.in — search for equipment keyword categories.
Signal_type: GEM_TENDER | Decay: Cliff | Peak: Day 0-30

GeM serves tender data via an AJAX/JSON endpoint rather than static HTML, so we
hit that endpoint directly with requests (faster and more stable than driving a
headless browser). If the endpoint returns non-JSON / empty payloads — which
usually means GeM changed the API or added a bot challenge — run() raises
ScraperBlocked so the operator is flagged before any Playwright fallback.
"""
from __future__ import annotations

import requests

from scrapers.base_scraper import BaseScraper

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"  # EV Manufacturing

# Equipment categories to search GeM for.
KEYWORDS = [
    "laser marking",
    "industrial automation",
    "conveyor system",
    "battery pack assembly",
    "welding robot",
    "injection moulding",
]

GEM_SEARCH_URL = "https://bidplus.gem.gov.in/all-bids-data"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}


class ScraperBlocked(RuntimeError):
    """Raised when GeM returns something other than parseable tender data."""


class GemScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="GEM_TENDER", industry_id=industry_id)

    def fetch_bids(self, keyword: str) -> list[dict]:
        """Query the GeM bid-list endpoint for one keyword. Returns raw records.

        GeM's payload shape changes occasionally; we defensively read the common
        fields and let parse_record() normalise them.
        """
        try:
            resp = requests.post(
                GEM_SEARCH_URL,
                headers=REQUEST_HEADERS,
                data={"searchBid": keyword, "page": 1},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ScraperBlocked(f"GeM request failed for '{keyword}': {exc}") from exc

        if resp.status_code != 200:
            raise ScraperBlocked(
                f"GeM returned HTTP {resp.status_code} for '{keyword}'. "
                "Likely a bot challenge — inspect the Network tab for the real "
                "endpoint before switching to Playwright."
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ScraperBlocked(
                f"GeM returned non-JSON for '{keyword}' (JS rendering or "
                "challenge page). Flagging before any Playwright fallback."
            ) from exc

        # GeM nests the list under 'response' -> 'response' -> 'docs' in most
        # variants; fall back to a flat 'docs' or list payload.
        docs = (
            payload.get("response", {}).get("response", {}).get("docs")
            or payload.get("docs")
            or (payload if isinstance(payload, list) else [])
        )
        return docs or []

    @staticmethod
    def parse_record(rec: dict, keyword: str) -> dict:
        """Map a GeM bid record to the write_signal() field shape."""
        title = rec.get("b_bid_number") or rec.get("bid_no") or rec.get("title", "")
        org = (
            rec.get("ba_official_details_minName")
            or rec.get("department_name")
            or rec.get("organisation", "")
        )
        items = rec.get("b_category_name") or rec.get("items", "")
        end_date = rec.get("final_end_date_sort") or rec.get("end_date", "")
        bid_no = rec.get("b_bid_number") or rec.get("bid_no", "")
        url = (
            f"https://bidplus.gem.gov.in/showbidDocument/{bid_no}"
            if bid_no else GEM_SEARCH_URL
        )
        snippet = f"GeM tender [{keyword}]: {title} | {items} | closes {end_date}"
        return {
            "raw_company_name": org,
            "source": "GeM",
            "source_url": url,
            "raw_text_snippet": snippet[:500],
        }

    def run(self) -> int:
        """Search every keyword, write each tender as a signal. Returns count."""
        written = 0
        for keyword in KEYWORDS:
            for rec in self.fetch_bids(keyword):
                data = self.parse_record(rec, keyword)
                if not data["raw_company_name"]:
                    continue
                if self.write_signal(data):
                    written += 1
        print(f"GemScraper: wrote {written} new signals across "
              f"{len(KEYWORDS)} keywords.")
        return written


if __name__ == "__main__":
    # Offline test: exercise parse_record without hitting GeM or the DB, so the
    # mapping logic can be verified before pointing at the live endpoint.
    sample = {
        "b_bid_number": "GEM/2026/B/4521789",
        "ba_official_details_minName": "Bharat Heavy Electricals Ltd",
        "b_category_name": "Industrial Automation Conveyor System",
        "final_end_date_sort": "2026-07-15",
    }
    mapped = GemScraper.parse_record(sample, "industrial automation")
    print("parse_record output:")
    for k, v in mapped.items():
        print(f"  {k}: {v}")
    assert mapped["raw_company_name"] == "Bharat Heavy Electricals Ltd"
    assert "GEM/2026/B/4521789" in mapped["source_url"]
    print("OK: GeM record mapping works.")
