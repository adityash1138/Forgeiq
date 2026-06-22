"""LinkedIn company-activity scraper — Tier 3.

Monitors company-page RSS (where available) / manual-monitor feeds for new
facility and hiring-push posts. LinkedIn is hostile to automated access, so this
is RSS / operator-curated rather than page scraping.
Signal_type: LINKEDIN_ACTIVITY | Decay: Cliff.
"""
from __future__ import annotations

from scrapers.base_scraper import BaseScraper
from scrapers._rss_base import extract_company, fetch_entries, matches_keywords

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

# Operator supplies company-page RSS URLs (e.g. via an RSS bridge) here.
FEEDS: list[str] = []
KEYWORDS = ["new facility", "we're hiring", "we are hiring", "now hiring",
            "expanding", "new plant", "grand opening", "inaugurated"]


class LinkedinScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID,
                 feeds: list[str] | None = None):
        super().__init__(signal_type="LINKEDIN_ACTIVITY", industry_id=industry_id)
        self.feeds = feeds if feeds is not None else FEEDS

    def run(self) -> int:
        if not self.feeds:
            print("LinkedinScraper: no feeds configured — skipping.")
            return 0
        written = 0
        for e in fetch_entries(self.feeds):
            text = f"{e['title']} {e['summary']}"
            if not matches_keywords(text, KEYWORDS):
                continue
            company = extract_company(text) or e.get("source_name")
            if not company:
                continue
            data = {
                "raw_company_name": company,
                "source": "LinkedIn",
                "source_url": e["link"],
                "raw_text_snippet": e["title"][:500],
            }
            if self.write_signal(data):
                written += 1
        print(f"LinkedinScraper: wrote {written} new activity signals.")
        return written


if __name__ == "__main__":
    text = "Ather Energy Ltd: We're hiring at our new facility in Hosur!"
    assert matches_keywords(text, KEYWORDS)
    assert extract_company(text) == "Ather Energy Ltd"
    print("OK: LinkedIn activity keyword + company extraction works.")
