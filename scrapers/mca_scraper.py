"""MCA / ROC filing scraper — Tier 2.

Target: MCA master-data / financial filings. Flags companies showing strong
financial-growth markers (revenue 30%+ growth, large fixed-asset additions),
which precede expansion purchasing.
Signal_type: MCA_ROC_FILING | Decay: Burn.

MCA has no clean public bulk API; in practice the operator supplies a watchlist
of CINs and we poll each company's master data. This scraper is therefore
watchlist-driven rather than discovery-driven.
"""
from __future__ import annotations

import requests

from scrapers.base_scraper import BaseScraper

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

MCA_MASTER_DATA_URL = (
    "https://www.mca.gov.in/bin/mca/getMasterData"  # illustrative endpoint
)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ForgeIQ/1.0)"}

# Growth markers that make a filing a buying-intent signal.
GROWTH_KEYWORDS = [
    "fixed asset", "capital work", "plant and machinery",
    "increase in authorised capital", "fresh allotment",
]


class McaScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID,
                 watchlist_cins: list[str] | None = None):
        super().__init__(signal_type="MCA_ROC_FILING", industry_id=industry_id)
        self.watchlist_cins = watchlist_cins or []

    def fetch_master_data(self, cin: str) -> dict | None:
        try:
            resp = requests.get(MCA_MASTER_DATA_URL, headers=HEADERS,
                                params={"cin": cin}, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"McaScraper: fetch failed for {cin}: {exc}")
            return None

    @staticmethod
    def is_growth_signal(record: dict) -> bool:
        # Explicit revenue-growth flag, or growth keywords in the filing text.
        growth_pct = record.get("revenue_growth_pct")
        if isinstance(growth_pct, (int, float)) and growth_pct >= 30:
            return True
        text = " ".join(str(v) for v in record.values()).lower()
        return any(kw in text for kw in GROWTH_KEYWORDS)

    @staticmethod
    def parse_record(record: dict, cin: str) -> dict:
        name = record.get("company_name") or record.get("name") or cin
        growth = record.get("revenue_growth_pct")
        detail = record.get("latest_filing_summary", "ROC filing")
        snippet = f"MCA/ROC filing: {name} — {detail}"
        if growth is not None:
            snippet += f" (revenue growth {growth}%)"
        return {
            "raw_company_name": name,
            "source": "MCA",
            "source_url": f"https://www.mca.gov.in/mcafoportal/"
                          f"viewCompanyMasterData.do?cin={cin}",
            "raw_text_snippet": snippet[:500],
        }

    def run(self) -> int:
        if not self.watchlist_cins:
            print("McaScraper: empty watchlist — nothing to poll.")
            return 0
        written = 0
        for cin in self.watchlist_cins:
            record = self.fetch_master_data(cin)
            if not record or not self.is_growth_signal(record):
                continue
            data = self.parse_record(record, cin)
            if self.write_signal(data):
                written += 1
        print(f"McaScraper: wrote {written} new MCA growth signals.")
        return written


if __name__ == "__main__":
    # Offline: growth detection + record mapping.
    growth = {"company_name": "Sona BLW Precision Forgings Ltd",
              "revenue_growth_pct": 42,
              "latest_filing_summary": "Additions to plant and machinery"}
    flat = {"company_name": "Static Co Ltd", "revenue_growth_pct": 5,
            "latest_filing_summary": "Routine annual return"}

    assert McaScraper.is_growth_signal(growth) is True
    assert McaScraper.is_growth_signal(flat) is False
    mapped = McaScraper.parse_record(growth, "U34100HR2013PLC123456")
    print(f"mapped: {mapped}")
    assert "42%" in mapped["raw_text_snippet"]
    print("OK: MCA growth detection + mapping works.")
