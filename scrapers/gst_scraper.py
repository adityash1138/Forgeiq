"""GST new-state-registration scraper — Tier 3.

A known company registering a new GSTIN in a new state often precedes a new
facility there. Watchlist-driven: the operator supplies known companies (PAN +
name) and we check for new state registrations via the public GST search.
Signal_type: GST_NEW_STATE | Decay: Cliff.
"""
from __future__ import annotations

import requests

from scrapers.base_scraper import BaseScraper

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

GST_SEARCH_API = "https://taxpayerapi.gst.gov.in/commonapi/v1.0/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ForgeIQ/1.0)",
           "Accept": "application/json"}

# GSTIN state code (first 2 digits) -> state, restricted to target states.
TARGET_STATE_CODES = {"27": "Maharashtra", "33": "Tamil Nadu",
                      "29": "Karnataka", "24": "Gujarat",
                      "36": "Telangana", "06": "Haryana"}


class GstScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID,
                 watchlist_pans: list[dict] | None = None):
        super().__init__(signal_type="GST_NEW_STATE", industry_id=industry_id)
        # each entry: {"pan": "ABCDE1234F", "name": "...", "known_states": ["27"]}
        self.watchlist = watchlist_pans or []

    def fetch_registrations(self, pan: str) -> list[dict]:
        try:
            resp = requests.get(GST_SEARCH_API, headers=HEADERS,
                                params={"pan": pan}, timeout=30)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"GstScraper: fetch failed for PAN {pan}: {exc}")
            return []

    @staticmethod
    def new_target_registrations(regs: list[dict],
                                 known_states: list[str]) -> list[dict]:
        """GSTINs in a target state the company wasn't previously known in."""
        out = []
        for r in regs:
            gstin = r.get("gstin", "")
            state_code = gstin[:2]
            if state_code in TARGET_STATE_CODES \
                    and state_code not in known_states:
                out.append({**r, "_state": TARGET_STATE_CODES[state_code]})
        return out

    def run(self) -> int:
        if not self.watchlist:
            print("GstScraper: empty watchlist — nothing to check.")
            return 0
        written = 0
        for entry in self.watchlist:
            regs = self.fetch_registrations(entry["pan"])
            for new in self.new_target_registrations(
                    regs, entry.get("known_states", [])):
                data = {
                    "raw_company_name": entry["name"],
                    "source": "GST",
                    "source_url": GST_SEARCH_API,
                    "raw_text_snippet": f"New GST registration in "
                                        f"{new['_state']}: {new.get('gstin')}",
                }
                if self.write_signal(data):
                    written += 1
        print(f"GstScraper: wrote {written} new GST-state signals.")
        return written


if __name__ == "__main__":
    regs = [{"gstin": "27ABCDE1234F1Z5"},   # Maharashtra (known)
            {"gstin": "33ABCDE1234F1Z5"},   # Tamil Nadu (new!)
            {"gstin": "19ABCDE1234F1Z5"}]   # West Bengal (not target)
    new = GstScraper.new_target_registrations(regs, known_states=["27"])
    print([n["_state"] for n in new])
    assert len(new) == 1 and new[0]["_state"] == "Tamil Nadu"
    print("OK: GST new-target-state detection works.")
