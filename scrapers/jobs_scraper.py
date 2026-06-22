"""Job postings scraper — Tier 2, free (with caveats).

Target: Naukri search pages (+ LinkedIn jobs RSS where available). Job boards
fight scraping harder than government portals, so we rotate User-Agents, add
polite delays, and stop after a block rather than hammering.
Signal_type: JOB_POSTING | Decay: Cliff | Peak: Day 0-60.
"""
from __future__ import annotations

import random
import time

import requests
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper

DEFAULT_INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"

# (keyword, city) pairs to search. Keep the list small — this is Tier 2.
SEARCHES = [
    ("plant-head", "pune"),
    ("automation-engineer", "chennai"),
    ("battery-pack-assembly", "bengaluru"),
    ("ev-manufacturing", "ahmedabad"),
    ("production-manager", "hosur"),
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

MIN_DELAY, MAX_DELAY = 5, 10  # seconds between requests


class JobsBlocked(RuntimeError):
    """Naukri served a CAPTCHA / 403 — stop and flag the operator."""


class JobsScraper(BaseScraper):
    def __init__(self, industry_id: str = DEFAULT_INDUSTRY_ID):
        super().__init__(signal_type="JOB_POSTING", industry_id=industry_id)

    def _headers(self) -> dict:
        return {"User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "en-US,en;q=0.9"}

    def fetch_search(self, keyword: str, city: str) -> bytes:
        url = f"https://www.naukri.com/{keyword}-jobs-in-{city}"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        if resp.status_code in (403, 429) or "captcha" in resp.text.lower():
            raise JobsBlocked(
                f"Naukri blocked the request for {keyword} in {city} "
                f"(HTTP {resp.status_code}). Reduce frequency / rotate UA / "
                "bookmark target-company pages instead of broad search."
            )
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def parse_jobs(html: bytes, keyword: str, city: str) -> list[dict]:
        """Extract (company, title, location) from Naukri job cards."""
        soup = BeautifulSoup(html, "lxml")
        out: list[dict] = []
        for card in soup.select("article.jobTuple, div.srp-jobtuple-wrapper"):
            title_el = card.select_one("a.title, a.jobTitle")
            comp_el = card.select_one("a.comp-name, a.subTitle")
            if not comp_el:
                continue
            company = comp_el.get_text(strip=True)
            title = title_el.get_text(strip=True) if title_el else keyword
            url = title_el["href"] if title_el and title_el.has_attr("href") else \
                f"https://www.naukri.com/{keyword}-jobs-in-{city}"
            out.append({
                "raw_company_name": company,
                "source": "Naukri",
                "source_url": url,
                "raw_text_snippet": f"Hiring [{city}]: {title} at {company}",
            })
        return out

    def run(self) -> int:
        written = 0
        for keyword, city in SEARCHES:
            try:
                html = self.fetch_search(keyword, city)
            except JobsBlocked as exc:
                print(f"JobsScraper: {exc}")
                break  # stop the whole run; a block won't clear mid-run
            for data in self.parse_jobs(html, keyword, city):
                if self.write_signal(data):
                    written += 1
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        print(f"JobsScraper: wrote {written} new job-posting signals.")
        return written


if __name__ == "__main__":
    # Offline: parse a representative Naukri job card without network.
    sample = b"""
    <article class="jobTuple">
      <a class="title" href="https://naukri.com/job-view/123">Plant Head - EV</a>
      <a class="comp-name">Ather Energy Pvt Ltd</a>
    </article>
    """
    jobs = JobsScraper.parse_jobs(sample, "plant-head", "pune")
    print(f"parsed jobs: {jobs}")
    assert jobs and jobs[0]["raw_company_name"] == "Ather Energy Pvt Ltd"
    assert "Plant Head" in jobs[0]["raw_text_snippet"]
    print("OK: Naukri job-card parsing works.")
