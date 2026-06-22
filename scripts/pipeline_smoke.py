"""End-to-end pipeline smoke test — drives the REAL engine code.

Unlike db/seed_demo.py (which hand-inserts finished scores and deliveries),
this script exercises the actual intelligence pipeline exactly as the daily
scheduler does, and asserts that a signal flows all the way to a delivered lead:

    raw signal  ->  entity resolution  ->  app tagging  ->  scoring  ->  delivery

It builds an isolated company + vendor (distinct UUIDs, prefix 0e/0f) so it
never collides with demo data, runs each pipeline stage in the scheduler's
canonical order, and verifies a HOT score and a lead_delivery row appear.

Usage (needs DATABASE_URL + an applied schema/seed_config):
    python -m scripts.pipeline_smoke

Network is never touched: contact sourcing and the live scrapers are bypassed;
we write the raw_signals directly via BaseScraper.write_signal, which is the
exact same intake path every real scraper uses.
"""
from __future__ import annotations

import sys
from datetime import date

from db.connection import fetch_all, fetch_one, get_cursor
from scrapers.base_scraper import BaseScraper

INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"  # EV Manufacturing
CATEGORY_ID = "00000000-0000-0000-0000-000000000010"  # from seed_demo
APP_CELL = "00000000-0000-0000-0000-000000000011"     # Battery Cell Assembly Line

# Isolated test fixtures (0e/0f prefixes — never used by demo data).
TEST_COMPANY = "0e000000-0000-0000-0000-000000000001"
TEST_VENDOR = "0f000000-0000-0000-0000-000000000001"
TEST_API_KEY = "fiq_pipeline_smoke"
COMPANY_NAME = "Hero MotoCorp Ltd"
COMPANY_CIN = "L35911DL1984PLC017354"
COMPANY_LOCATION = "Gurugram, Haryana"


class _DirectScraper(BaseScraper):
    """A minimal scraper used only to push fixture signals through real intake."""
    def run(self):  # pragma: no cover - not used
        raise NotImplementedError


def _require_prerequisites() -> None:
    if not fetch_one("SELECT 1 FROM signal_type_config WHERE signal_type='GEM_TENDER'"):
        sys.exit("seed_config not applied — run db/seed_config.sql first.")
    if not fetch_one("SELECT 1 FROM applications WHERE id = %s", (APP_CELL,)):
        sys.exit("Battery Cell Assembly Line app missing — run db.seed_demo first.")


def _reset_fixtures() -> None:
    """Make the run idempotent: clear any prior test rows (FK-safe order)."""
    with get_cursor() as cur:
        cur.execute(
            "DELETE FROM lead_delivery WHERE vendor_id = %s", (TEST_VENDOR,))
        cur.execute(
            "DELETE FROM lead_delivery ld USING scores s "
            "WHERE ld.score_id = s.id AND s.company_id = %s", (TEST_COMPANY,))
        cur.execute("DELETE FROM scores WHERE company_id = %s", (TEST_COMPANY,))
        cur.execute(
            "DELETE FROM entity_resolution_queue WHERE best_guess_company_id = %s "
            "OR signal_id IN (SELECT id FROM raw_signals WHERE resolved_company_id = %s)",
            (TEST_COMPANY, TEST_COMPANY))
        cur.execute("DELETE FROM raw_signals WHERE raw_company_name = %s",
                    (COMPANY_NAME,))
        cur.execute("DELETE FROM contacts WHERE company_id = %s", (TEST_COMPANY,))
        cur.execute("DELETE FROM vendors WHERE id = %s", (TEST_VENDOR,))
        cur.execute("DELETE FROM companies WHERE id = %s", (TEST_COMPANY,))


def _setup_fixtures() -> None:
    with get_cursor() as cur:
        # A company that already exists → structured_match resolves Tier A.
        cur.execute(
            "INSERT INTO companies (id, industry_id, legal_name, cin, plant_location) "
            "VALUES (%s, %s, %s, %s, %s)",
            (TEST_COMPANY, INDUSTRY_ID, COMPANY_NAME, COMPANY_CIN, COMPANY_LOCATION))
        # A Standard-tier vendor that matches the battery app + Haryana geography.
        # Standard (not Premium) so the lead is actually delivered, not just flagged.
        cur.execute(
            "INSERT INTO vendors (id, vendor_name, industry_id, application_id, "
            "price_tier, geography, onboarding_complete, api_key) "
            "VALUES (%s, 'Smoke Test Equipment Co', %s, %s, 'Standard', %s, TRUE, %s)",
            (TEST_VENDOR, INDUSTRY_ID, APP_CELL, ["Haryana"], TEST_API_KEY))
        # A contact so the delivered lead carries contact_ids.
        cur.execute(
            "INSERT INTO contacts (company_id, full_name, role, confidence_tier, "
            "source, email_pattern_guess) VALUES (%s, 'Test Contact', "
            "'VP Manufacturing', 'High', 'Smoke', 'test.contact@heromotocorp.com')",
            (TEST_COMPANY,))


def _ingest_signals() -> list[str]:
    """Push 3 Tier-1 signals through the real intake path. All peak at day 0:
       GEM_TENDER(8) + PLI_APPROVAL(9) + ICEGATE_IMPORT(8) = raw 25 → norm 71 → HOT.
       Battery keywords ensure all three tag the Battery Cell Assembly Line app.
    """
    today = date.today()
    specs = [
        ("GEM_TENDER",     "GeM tender for battery cell assembly line equipment"),
        ("PLI_APPROVAL",   "ACC battery PLI approval for new lithium cell unit"),
        ("ICEGATE_IMPORT", "Import of lithium battery cell manufacturing machinery"),
    ]
    ids = []
    for sig_type, snippet in specs:
        scraper = _DirectScraper(signal_type=sig_type, industry_id=INDUSTRY_ID)
        sid = scraper.write_signal({
            "raw_company_name": COMPANY_NAME,
            "source": "SmokeTest",
            "source_url": f"https://smoke.test/{sig_type}",
            "raw_text_snippet": snippet,
            "date_detected": today,
        })
        ids.append(sid)
    return ids


def _run_pipeline() -> None:
    """Run the engine stages in the scheduler's canonical order (no network)."""
    from processing import app_tagger, entity_resolver
    from engine import scoring_engine
    from delivery import lead_router

    app_tagger.tag_new_signals()
    entity_resolver.resolve_new_signals()
    scoring_engine.recalculate_all_due()
    lead_router.route_hot_scores()


def _verify() -> None:
    # 1. Signals resolved to the company at Tier A.
    sigs = fetch_all(
        "SELECT signal_type, resolution_tier, resolved_company_id, application_tags "
        "FROM raw_signals WHERE raw_company_name = %s", (COMPANY_NAME,))
    assert len(sigs) == 3, f"expected 3 signals, got {len(sigs)}"
    for s in sigs:
        assert str(s["resolved_company_id"]) == TEST_COMPANY, \
            f"{s['signal_type']} did not resolve to test company"
        assert s["resolution_tier"] == "A", \
            f"{s['signal_type']} tier={s['resolution_tier']} (expected A)"
        assert s["application_tags"] and APP_CELL in [str(t) for t in s["application_tags"]], \
            f"{s['signal_type']} not tagged to battery app"
    print(f"  [1/3] 3 signals resolved Tier A and tagged to battery app ✓")

    # 2. Score for the battery app is HOT.
    score = fetch_one(
        "SELECT current_score, status FROM scores "
        "WHERE company_id = %s AND application_id = %s", (TEST_COMPANY, APP_CELL))
    assert score, "no score row produced"
    assert score["status"] == "HOT", \
        f"score {score['current_score']} status={score['status']} (expected HOT)"
    print(f"  [2/3] score = {float(score['current_score'])} → "
          f"{score['status']} (raw 25/35 → ~71) ✓")

    # 3. A lead was delivered to the test vendor.
    lead = fetch_one(
        "SELECT ld.id, ld.confidence_tier_shown, ld.contact_ids, ld.why_explanation "
        "FROM lead_delivery ld JOIN scores s ON s.id = ld.score_id "
        "WHERE ld.vendor_id = %s AND s.company_id = %s", (TEST_VENDOR, TEST_COMPANY))
    assert lead, "no lead delivered to the test vendor"
    assert lead["contact_ids"], "delivered lead carries no contacts"
    print(f"  [3/3] lead delivered to vendor (tier shown="
          f"{lead['confidence_tier_shown']}, "
          f"{len(lead['contact_ids'])} contact[s]) ✓")


def main() -> None:
    print("ForgeIQ end-to-end pipeline smoke test")
    print("=" * 44)
    _require_prerequisites()
    _reset_fixtures()
    _setup_fixtures()
    print("Fixtures ready (isolated company + Standard vendor).")
    print("Ingesting 3 Tier-1 signals via real BaseScraper intake…")
    _ingest_signals()
    print("Running pipeline (tag → resolve → score → route)…")
    _run_pipeline()
    print("Verifying:")
    _verify()
    print("=" * 44)
    print("PASS — signal flowed end-to-end to a delivered lead.")


if __name__ == "__main__":
    main()
