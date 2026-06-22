"""OEM contract-win scraper — Tier 2.

Monitors BSE announcements + Google News RSS for EV OEM supply agreements.
Signal_type: OEM_CONTRACT_WIN | Decay: Cliff.
"""
from __future__ import annotations

from scrapers.base_scraper import BaseScraper
from scrapers._rss_base import extract_company, fetch_entries, matches_keywords

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

OEM_NAMES = ["Tata Motors", "Mahindra", "Ola Electric", "Ather", "TVS",
             "Bajaj", "Hyundai", "Maruti", "Ashok Leyland"]
FEEDS = [
    "https://news.google.com/rss/search?q=" +
    "EV+supply+agreement+OR+contract+win+India&hl=en-IN&gl=IN&ceid=IN:en",
]
KEYWORDS = ["supply agreement", "contract win", "order win", "to supply",
            "bags order", "wins contract"]


class OemNewsScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="OEM_CONTRACT_WIN", industry_id=industry_id)

    def run(self) -> int:
        written = 0
        for e in fetch_entries(FEEDS):
            text = f"{e['title']} {e['summary']}"
            if not matches_keywords(text, KEYWORDS):
                continue
            company = extract_company(text)
            if not company:
                continue
            data = {
                "raw_company_name": company,
                "source": "OEM News",
                "source_url": e["link"],
                "raw_text_snippet": e["title"][:500],
            }
            if self.write_signal(data):
                written += 1
        print(f"OemNewsScraper: wrote {written} new OEM contract signals.")
        return written


if __name__ == "__main__":
    assert matches_keywords("Sona BLW bags order to supply EV motors", KEYWORDS)
    assert extract_company("Sona BLW Precision Forgings Ltd wins contract") \
        == "Sona BLW Precision Forgings Ltd"
    print("OK: OEM contract keyword + company extraction works.")
