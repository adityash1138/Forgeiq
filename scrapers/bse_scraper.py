"""BSE/NSE CAPEX filing scraper — Tier 1, free.

Target: BSE corporate-announcements public API (+ NSE as a secondary source).
Filters announcements for CAPEX / capacity-expansion keywords.
Signal_type: CAPEX_FILING | Decay: Wave | Peak: Month 4-9 | Cascade trigger.
"""
from __future__ import annotations

import requests

from scrapers.base_scraper import BaseScraper

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

# BSE's public announcements endpoint returns JSON.
BSE_ANN_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
}

CAPEX_KEYWORDS = [
    "capex", "capacity expansion", "greenfield", "new plant",
    "manufacturing facility", "new facility", "capital expenditure",
    "setting up", "brownfield expansion",
]


class BseScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="CAPEX_FILING", industry_id=industry_id)

    def fetch_announcements(self, page: int = 1) -> list[dict]:
        """Fetch one page of corporate announcements as JSON records."""
        params = {
            "pageno": page,
            "strCat": "-1",          # all categories
            "strPrevDate": "",
            "strScrip": "",
            "strSearch": "P",
            "strToDate": "",
            "strType": "C",
        }
        try:
            resp = requests.get(BSE_ANN_URL, headers=BSE_HEADERS,
                                params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"BseScraper: fetch failed (page {page}): {exc}")
            return []
        return payload.get("Table", []) or []

    @staticmethod
    def matches_capex(text: str) -> bool:
        low = (text or "").lower()
        return any(kw in low for kw in CAPEX_KEYWORDS)

    @staticmethod
    def parse_record(rec: dict) -> dict:
        company = rec.get("SLONGNAME") or rec.get("NAME") or ""
        headline = rec.get("HEADLINE") or rec.get("NEWSSUB") or ""
        body = rec.get("MORE") or rec.get("NEWSBODY") or ""
        news_id = rec.get("NEWSID") or rec.get("NSURL") or ""
        url = (
            f"https://www.bseindia.com/corporates/anndet_new.aspx?newsid={news_id}"
            if news_id else "https://www.bseindia.com/"
        )
        snippet = f"{headline} {body}".strip()
        return {
            "raw_company_name": company.strip(),
            "source": "BSE",
            "source_url": url,
            "raw_text_snippet": snippet[:500],
        }

    def run(self, max_pages: int = 3) -> int:
        written = 0
        for page in range(1, max_pages + 1):
            for rec in self.fetch_announcements(page):
                headline = rec.get("HEADLINE") or rec.get("NEWSSUB") or ""
                body = rec.get("MORE") or rec.get("NEWSBODY") or ""
                if not self.matches_capex(f"{headline} {body}"):
                    continue
                data = self.parse_record(rec)
                if not data["raw_company_name"]:
                    continue
                if self.write_signal(data):
                    written += 1
        print(f"BseScraper: wrote {written} new CAPEX signals.")
        return written


if __name__ == "__main__":
    # Offline test: CAPEX keyword filter + record mapping, no DB/network.
    hit = {
        "SLONGNAME": "Amara Raja Energy & Mobility Ltd",
        "HEADLINE": "Board approves Rs 9500 cr CAPEX for new Giga battery plant",
        "MORE": "greenfield manufacturing facility in Telangana",
        "NEWSID": "abc123",
    }
    miss = {"SLONGNAME": "X Ltd", "HEADLINE": "Outcome of board meeting - dividend"}

    assert BseScraper.matches_capex(hit["HEADLINE"]) is True
    assert BseScraper.matches_capex(miss["HEADLINE"]) is False
    mapped = BseScraper.parse_record(hit)
    print("parse_record output:")
    for k, v in mapped.items():
        print(f"  {k}: {v}")
    assert mapped["raw_company_name"] == "Amara Raja Energy & Mobility Ltd"
    print("OK: BSE CAPEX filtering + mapping works.")
