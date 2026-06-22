"""ICEGATE import-data scraper — Tier 1, PAID (Zauba / Volza API).

Filters import shipments by HS code (equipment categories) and consignee state.
Signal_type: ICEGATE_IMPORT | Decay: Wave | Peak: Month 0-4 | Cascade trigger.

NOTE: the paid vendor's real field names are the source of truth. The mapping
below is a starting point — replace the keys in parse_record() with the actual
fields from a real sample response before going live.
"""
from __future__ import annotations

import os

import requests

from scrapers.base_scraper import BaseScraper

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

ZAUBA_API_URL = "https://api.zauba.com/v1/imports"  # confirm with vendor docs

HS_CODE_LIST = [
    "8479",  # machines with individual functions (automation)
    "8543",  # electrical machines (battery equipment)
    "8515",  # welding machines
    "8462",  # metal-forming / press
]
TARGET_STATES = ["Maharashtra", "Tamil Nadu", "Karnataka", "Gujarat",
                 "Telangana", "Haryana"]


class IcegateScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="ICEGATE_IMPORT", industry_id=industry_id)
        self.api_key = os.environ.get("ZAUBA_API_KEY")

    def fetch_shipments(self, hs_code: str) -> list[dict]:
        if not self.api_key:
            print("IcegateScraper: ZAUBA_API_KEY not set — skipping.")
            return []
        try:
            resp = requests.get(
                ZAUBA_API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={"hs_code": hs_code, "country": "India"},
                timeout=45)
            resp.raise_for_status()
            return resp.json().get("records", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"IcegateScraper: fetch failed for HS {hs_code}: {exc}")
            return []

    @staticmethod
    def in_target_state(rec: dict) -> bool:
        addr = (rec.get("consignee_address") or rec.get("address") or "").lower()
        return any(state.lower() in addr for state in TARGET_STATES)

    @staticmethod
    def parse_record(rec: dict) -> dict:
        consignee = rec.get("consignee_name") or rec.get("importer") or ""
        product = rec.get("product_description") or rec.get("goods") or ""
        hs = rec.get("hs_code") or ""
        return {
            "raw_company_name": consignee,
            "source": "ICEGATE/Zauba",
            "source_url": ZAUBA_API_URL,
            "raw_text_snippet": f"Import [HS {hs}]: {product}"[:500],
        }

    def run(self) -> int:
        written = 0
        for hs_code in HS_CODE_LIST:
            for rec in self.fetch_shipments(hs_code):
                if not self.in_target_state(rec):
                    continue
                data = self.parse_record(rec)
                if data["raw_company_name"] and self.write_signal(data):
                    written += 1
        print(f"IcegateScraper: wrote {written} new import signals.")
        return written


if __name__ == "__main__":
    rec = {"consignee_name": "Exide Industries Ltd",
           "consignee_address": "Plot 12, Pune, Maharashtra",
           "product_description": "Automated battery assembly line",
           "hs_code": "8479"}
    assert IcegateScraper.in_target_state(rec) is True
    assert IcegateScraper.in_target_state(
        {"consignee_address": "Dhaka, Bangladesh"}) is False
    mapped = IcegateScraper.parse_record(rec)
    print(mapped)
    assert mapped["raw_company_name"] == "Exide Industries Ltd"
    print("OK: ICEGATE state filter + mapping works.")
