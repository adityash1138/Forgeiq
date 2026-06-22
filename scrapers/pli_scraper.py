"""PLI scheme approval scraper — Tier 1, free.

Target: DPIIT / Make-in-India / sector PLI portals. Beneficiary lists are
published as HTML tables or PDFs; PDFs are parsed with pdfplumber.
Signal_type: PLI_APPROVAL | Decay: Wave | Peak: Month 0-6 | Cascade trigger.
"""
from __future__ import annotations

import io

import requests

from scrapers.base_scraper import BaseScraper

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

# Each entry is one official beneficiary source to parse.
PLI_SOURCES = [
    {
        "name": "Auto PLI (DPIIT)",
        "url": "https://dpiit.gov.in/sites/default/files/PLI_Auto_Beneficiaries.pdf",
        "type": "pdf",
    },
    {
        "name": "ACC Battery PLI",
        "url": "https://www.makeinindia.com/acc-battery-pli-beneficiaries",
        "type": "html",
    },
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ForgeIQ/1.0)"}


class PliScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="PLI_APPROVAL", industry_id=industry_id)

    def _parse_pdf(self, content: bytes) -> list[str]:
        """Extract approved company names from a beneficiary-list PDF."""
        import pdfplumber

        names: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for row in table:
                        name = self._company_cell(row)
                        if name:
                            names.append(name)
        return names

    def _parse_html(self, content: bytes) -> list[str]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "lxml")
        names: list[str] = []
        for tr in soup.select("table tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(("td", "th"))]
            name = self._company_cell(cells)
            if name:
                names.append(name)
        return names

    @staticmethod
    def _company_cell(row: list) -> str | None:
        """Heuristic: pick the cell that looks like a company name.

        Skips header rows, serial numbers, and empty cells. Company names in
        these lists typically contain 'Ltd', 'Limited', 'Pvt', 'India', etc.
        """
        markers = ("ltd", "limited", "pvt", "private", "india", "motors",
                   "energy", "technolog", "industries", "manufactur")
        for cell in row:
            text = (cell or "").strip()
            low = text.lower()
            if len(text) > 4 and any(m in low for m in markers):
                return text
        return None

    def fetch_and_parse(self, source: dict) -> list[str]:
        try:
            resp = requests.get(source["url"], headers=HEADERS, timeout=45)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"PliScraper: fetch failed for {source['name']}: {exc}")
            return []
        if source["type"] == "pdf":
            return self._parse_pdf(resp.content)
        return self._parse_html(resp.content)

    def run(self) -> int:
        written = 0
        for source in PLI_SOURCES:
            for name in self.fetch_and_parse(source):
                data = {
                    "raw_company_name": name,
                    "source": source["name"],
                    "source_url": source["url"],
                    "raw_text_snippet": f"PLI beneficiary approved: {name} "
                                        f"({source['name']})",
                }
                if self.write_signal(data):
                    written += 1
        print(f"PliScraper: wrote {written} new PLI approval signals.")
        return written


if __name__ == "__main__":
    # Offline: verify the company-cell heuristic on representative table rows.
    rows = [
        ["1", "Tata Motors Ltd", "Champion OEM", "Rs 1000 cr"],
        ["S.No", "Company Name", "Category", "Committed Investment"],  # header
        ["2", "Ola Electric Technologies Pvt Ltd", "Champion OEM", ""],
        ["3", "", "", ""],
    ]
    extracted = [PliScraper._company_cell(r) for r in rows]
    print(f"extracted: {extracted}")
    assert extracted[0] == "Tata Motors Ltd"
    assert extracted[1] is None      # header skipped
    assert extracted[2] == "Ola Electric Technologies Pvt Ltd"
    assert extracted[3] is None      # empty skipped
    print("OK: PLI company-cell extraction works.")
