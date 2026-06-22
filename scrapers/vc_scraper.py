"""VC/PE funding round scraper — Tier 2.

Monitors Tracxn / ET / news RSS for Auto, EV, and Manufacturing funding rounds.
Signal_type: VC_PE_FUNDING | Decay: Cliff.
"""
from __future__ import annotations

from scrapers.base_scraper import BaseScraper
from scrapers._rss_base import extract_company, fetch_entries, matches_keywords

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

FEEDS = [
    "https://news.google.com/rss/search?q="
    "EV+OR+manufacturing+startup+funding+round+India&hl=en-IN&gl=IN&ceid=IN:en",
    "https://economictimes.indiatimes.com/small-biz/sme-sector/rssfeeds/"
    "11993050.cms",
]
KEYWORDS = ["raises", "funding round", "series a", "series b", "series c",
            "led by", "valuation", "investment of", "secures funding"]
SECTOR_HINTS = ["ev", "electric", "auto", "manufactur", "battery", "mobility"]


class VcScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="VC_PE_FUNDING", industry_id=industry_id)

    def run(self) -> int:
        written = 0
        for e in fetch_entries(FEEDS):
            text = f"{e['title']} {e['summary']}"
            if not matches_keywords(text, KEYWORDS):
                continue
            if not matches_keywords(text, SECTOR_HINTS):
                continue  # ignore funding outside our sectors
            company = extract_company(text)
            if not company:
                continue
            data = {
                "raw_company_name": company,
                "source": "VC/PE News",
                "source_url": e["link"],
                "raw_text_snippet": e["title"][:500],
            }
            if self.write_signal(data):
                written += 1
        print(f"VcScraper: wrote {written} new funding signals.")
        return written


if __name__ == "__main__":
    text = "Ola Electric Mobility Ltd raises Series D funding in EV push"
    assert matches_keywords(text, KEYWORDS)
    assert matches_keywords(text, SECTOR_HINTS)
    assert extract_company(text) == "Ola Electric Mobility Ltd"
    print("OK: VC funding keyword + sector + company extraction works.")
