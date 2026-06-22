"""Land / factory acquisition scraper — Tier 2.

MIDC / SIPCOT industrial-land allotment notices (PDF/HTML) + news monitoring for
plant/factory land in target states.
Signal_type: LAND_ACQUISITION | Decay: Wave | Cascade trigger.
"""
from __future__ import annotations

import io

import requests

from scrapers.base_scraper import BaseScraper
from scrapers._rss_base import extract_company, fetch_entries, matches_keywords

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ForgeIQ/1.0)"}

# Industrial-development-authority allotment notice PDFs (operator-maintained).
ALLOTMENT_PDFS = [
    "https://www.midcindia.org/allotment-notices.pdf",
]
NEWS_FEEDS = [
    "https://news.google.com/rss/search?q="
    "factory+land+acquisition+OR+plant+land+allotment+India&hl=en-IN&gl=IN&ceid=IN:en",
]
KEYWORDS = ["land allotment", "acquires land", "land acquisition", "plot",
            "industrial land", "factory land", "leases land", "sq metres",
            "acres for plant"]
TARGET_STATES = ["Maharashtra", "Tamil Nadu", "Karnataka", "Gujarat",
                 "Telangana", "Haryana"]


class LandScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="LAND_ACQUISITION", industry_id=industry_id)

    def _parse_allotment_pdf(self, content: bytes) -> list[str]:
        import pdfplumber
        names: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for row in table:
                        for cell in row:
                            company = extract_company(cell or "")
                            if company:
                                names.append(company)
        return names

    def _run_pdfs(self) -> int:
        written = 0
        for url in ALLOTMENT_PDFS:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=45)
                resp.raise_for_status()
            except requests.RequestException as exc:
                print(f"LandScraper: PDF fetch failed {url}: {exc}")
                continue
            for name in self._parse_allotment_pdf(resp.content):
                data = {"raw_company_name": name, "source": "Industrial allotment",
                        "source_url": url,
                        "raw_text_snippet": f"Industrial land allotment: {name}"}
                if self.write_signal(data):
                    written += 1
        return written

    def _run_news(self) -> int:
        written = 0
        for e in fetch_entries(NEWS_FEEDS):
            text = f"{e['title']} {e['summary']}"
            if not matches_keywords(text, KEYWORDS):
                continue
            company = extract_company(text)
            if not company:
                continue
            data = {"raw_company_name": company, "source": "Land News",
                    "source_url": e["link"],
                    "raw_text_snippet": e["title"][:500]}
            if self.write_signal(data):
                written += 1
        return written

    def run(self) -> int:
        written = self._run_pdfs() + self._run_news()
        print(f"LandScraper: wrote {written} new land-acquisition signals.")
        return written


if __name__ == "__main__":
    text = "Tata Motors Ltd acquires 250 acres for plant in Tamil Nadu"
    assert matches_keywords(text, KEYWORDS)
    assert extract_company(text) == "Tata Motors Ltd"
    print("OK: land-acquisition keyword + company extraction works.")
