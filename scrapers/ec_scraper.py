"""Environmental Clearance (EC) filing scraper — Tier 2.

Target: parivesh.nic.in (MoEF EC portal). Manufacturing-sector proposals in
target states signal an imminent new/expanded facility.
Signal_type: EC_CLEARANCE | Decay: Burn | Cascade trigger.
"""
from __future__ import annotations

import requests

from scrapers.base_scraper import BaseScraper

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

PARIVESH_API = "https://parivesh.nic.in/parivesh_api/proponentApplicant/getProposalList"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ForgeIQ/1.0)",
           "Accept": "application/json"}

SECTOR_KEYWORDS = ["manufactur", "industrial", "automobile", "battery",
                   "vehicle", "component", "machinery", "plant"]
TARGET_STATES = ["Maharashtra", "Tamil Nadu", "Karnataka", "Gujarat",
                 "Telangana", "Haryana"]


class EcScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="EC_CLEARANCE", industry_id=industry_id)

    def fetch_proposals(self) -> list[dict]:
        try:
            resp = requests.get(PARIVESH_API, headers=HEADERS,
                                params={"sector": "Industrial Projects"},
                                timeout=45)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"EcScraper: fetch failed: {exc}")
            return []
        return payload.get("data", payload.get("proposals", [])) or []

    @staticmethod
    def is_relevant(rec: dict) -> bool:
        text = " ".join(str(v) for v in rec.values()).lower()
        sector_ok = any(k in text for k in SECTOR_KEYWORDS)
        state_ok = any(s.lower() in text for s in TARGET_STATES)
        return sector_ok and state_ok

    @staticmethod
    def parse_record(rec: dict) -> dict:
        company = (rec.get("companyName") or rec.get("proponent")
                   or rec.get("company_name") or "")
        project = rec.get("projectName") or rec.get("project") or ""
        pid = rec.get("proposalNo") or rec.get("id") or ""
        return {
            "raw_company_name": company,
            "source": "PARIVESH EC",
            "source_url": f"https://parivesh.nic.in/proposal/{pid}"
                          if pid else PARIVESH_API,
            "raw_text_snippet": f"EC proposal: {project} ({company})"[:500],
        }

    def run(self) -> int:
        written = 0
        for rec in self.fetch_proposals():
            if not self.is_relevant(rec):
                continue
            data = self.parse_record(rec)
            if data["raw_company_name"] and self.write_signal(data):
                written += 1
        print(f"EcScraper: wrote {written} new EC clearance signals.")
        return written


if __name__ == "__main__":
    rec = {"companyName": "Exide Industries Ltd",
           "projectName": "Lithium battery manufacturing unit",
           "state": "Karnataka", "proposalNo": "EC2026123"}
    assert EcScraper.is_relevant(rec) is True
    assert EcScraper.is_relevant(
        {"projectName": "Mining lease", "state": "Odisha"}) is False
    mapped = EcScraper.parse_record(rec)
    print(mapped)
    assert mapped["raw_company_name"] == "Exide Industries Ltd"
    print("OK: EC sector+state relevance + mapping works.")
