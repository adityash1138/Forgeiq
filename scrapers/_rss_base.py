"""Shared RSS helper for the news-style scrapers (OEM news, VC, News, LinkedIn).

Keeps feed-fetching and company-name extraction in one place so each RSS-based
scraper stays a thin configuration of feeds + keywords + a company matcher.
"""
from __future__ import annotations

import re

import feedparser

# Company-suffix markers used to pull a company name out of a headline.
_COMPANY_RE = re.compile(
    r"([A-Z][A-Za-z&.\-]+(?:\s+[A-Z][A-Za-z&.\-]+){0,4}\s+"
    r"(?:Ltd|Limited|Pvt|Private|Industries|Motors|Energy|Technologies|"
    r"Mobility|Electric|Automotive|Auto))"
)


def fetch_entries(feed_urls: list[str]) -> list[dict]:
    """Return parsed entries (title, summary, link) across all feeds."""
    entries: list[dict] = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
        except Exception as exc:  # noqa: BLE001
            print(f"_rss_base: failed to parse {url}: {exc}")
            continue
        for e in parsed.entries:
            entries.append({
                "title": getattr(e, "title", ""),
                "summary": getattr(e, "summary", ""),
                "link": getattr(e, "link", ""),
            })
    return entries


def extract_company(text: str) -> str | None:
    """Best-effort company-name extraction from a headline/summary."""
    m = _COMPANY_RE.search(text or "")
    return m.group(1).strip() if m else None


def matches_keywords(text: str, keywords: list[str]) -> bool:
    low = (text or "").lower()
    return any(kw in low for kw in keywords)
