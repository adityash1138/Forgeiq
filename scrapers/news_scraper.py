"""News-mention scraper — Tier 3.

Google News + Economic Times RSS for company expansion / investment mentions.
Signal_type: NEWS_MENTION | Decay: Cliff.
"""
from __future__ import annotations

from scrapers.base_scraper import BaseScraper
from scrapers._rss_base import extract_company, fetch_entries, matches_keywords

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

FEEDS = [
    "https://news.google.com/rss/search?q="
    "manufacturing+expansion+OR+new+plant+investment+India&hl=en-IN&gl=IN&ceid=IN:en",
    "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
]
KEYWORDS = ["expansion", "investment", "new plant", "to invest", "capacity",
            "manufacturing", "facility", "to set up"]


class NewsScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="NEWS_MENTION", industry_id=industry_id)

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
                "source": "News",
                "source_url": e["link"],
                "raw_text_snippet": e["title"][:500],
            }
            if self.write_signal(data):
                written += 1
        print(f"NewsScraper: wrote {written} new news-mention signals.")
        return written


if __name__ == "__main__":
    text = "Amara Raja Energy Ltd to invest Rs 9500 cr in new battery plant"
    assert matches_keywords(text, KEYWORDS)
    assert extract_company(text) == "Amara Raja Energy Ltd"
    print("OK: news-mention keyword + company extraction works.")
