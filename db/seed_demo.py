"""Demo-data seeder for ForgeIQ.

Populates the database with realistic sample applications, a demo vendor,
companies, scores, contacts and delivered leads so the vendor dashboard shows
real-looking data immediately — before any scraper has run.

Idempotent: every row uses a fixed UUID (or a unique key) with ON CONFLICT,
so you can run this repeatedly without creating duplicates.

Usage:
    python -m db.seed_demo          # after the schema + seed_config are applied

Then log into the dashboard at http://localhost:8000 with the API key it prints.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from db.connection import get_cursor

INDUSTRY_ID = "00000000-0000-0000-0000-000000000001"  # EV Manufacturing (seed_config)
DEMO_API_KEY = "fiq_demo_key_2026"

# Fixed UUIDs keep the seed idempotent.
CATEGORY_ID = "00000000-0000-0000-0000-000000000010"
APP_CELL = "00000000-0000-0000-0000-000000000011"
APP_PACK = "00000000-0000-0000-0000-000000000012"
APP_BODY = "00000000-0000-0000-0000-000000000013"
VENDOR_ID = "00000000-0000-0000-0000-000000000020"

now = datetime.now(timezone.utc)


def _company_uuid(n: int) -> str:
    return f"00000000-0000-0000-0000-0000000001{n:02d}"


def _score_uuid(n: int) -> str:
    return f"00000000-0000-0000-0000-0000000002{n:02d}"


def _delivery_uuid(n: int) -> str:
    return f"00000000-0000-0000-0000-0000000003{n:02d}"


def _contact_uuid(n: int) -> str:
    return f"00000000-0000-0000-0000-0000000004{n:02d}"


# (company_n, legal_name, cin, plant_location, app_id, score, status, tier,
#  exclusivity_hours_left, why, contacts[(name, role, email_guess, tier)])
DEMO = [
    (1, "Ather Energy Ltd", "U40100KA2013PTC000001", "Hosur, Tamil Nadu",
     APP_CELL, 84.0, "HOT", "Premium", 60,
     "Why this lead — Ather Energy Ltd (Battery Cell Assembly Line)\n\n"
     "• 12 Jun 2026 — CAPEX_FILING (Tier 1): BSE filing announces ₹650cr "
     "expansion for a new cell line in Hosur.\n"
     "• 18 Jun 2026 — LAND_ACQUISITION (Tier 2): 40-acre SIPCOT allotment "
     "confirmed adjacent to existing plant.\n"
     "• 20 Jun 2026 — JOB_POSTING (Tier 3): 14 openings for cell-line "
     "process engineers in Hosur.\n\n"
     "Cascade: land + CAPEX within the activation window confirmed wave 1.",
     [("Rajesh Kumar", "VP Manufacturing", "rajesh.kumar@atherenergy.com", "High"),
      ("Priya Nair", "Head of Procurement", "priya.nair@atherenergy.com", "Medium")]),

    (2, "Exide Industries Ltd", "L31402WB1947PLC000002", "Bengaluru, Karnataka",
     APP_CELL, 76.0, "HOT", "Standard", 30,
     "Why this lead — Exide Industries Ltd (Battery Cell Assembly Line)\n\n"
     "• 05 Jun 2026 — PLI_APPROVAL (Tier 1): listed in the ACC battery PLI "
     "beneficiary update.\n"
     "• 14 Jun 2026 — EC_CLEARANCE (Tier 2): environmental clearance for a "
     "lithium-cell unit in Karnataka.\n",
     [("Suresh Menon", "Plant Director", "suresh.menon@exide.in", "High")]),

    (3, "Ola Electric Mobility Ltd", "U34100KA2017PTC000003", "Krishnagiri, Tamil Nadu",
     APP_PACK, 71.0, "HOT", "Premium", 48,
     "Why this lead — Ola Electric (Battery Pack Assembly)\n\n"
     "• 10 Jun 2026 — ICEGATE_IMPORT (Tier 1): import of pack-assembly "
     "machinery (HS 8479) at Chennai port.\n"
     "• 16 Jun 2026 — OEM_SUPPLY_NEWS (Tier 2): announced in-house pack "
     "line ramp-up.\n",
     [("Anil Sharma", "Head of Battery Engineering", "anil.sharma@olaelectric.com", "High")]),

    (4, "Tata Motors Ltd", "L28920MH1945PLC000004", "Pune, Maharashtra",
     APP_BODY, 58.0, "WARM", "Value", 24,
     "Why this lead — Tata Motors (Body/Chassis Welding Line)\n\n"
     "• 02 Jun 2026 — CAPEX_FILING (Tier 1): board approves EV body-shop "
     "modernisation at Pune.\n"
     "• 19 Jun 2026 — JOB_POSTING (Tier 3): welding-line automation roles "
     "posted.\n",
     [("Vikram Patil", "GM Body Shop", "vikram.patil@tatamotors.com", "Medium")]),

    (5, "Mahindra Electric Ltd", "U34100MH2010PTC000005", "Chakan, Maharashtra",
     APP_BODY, 47.0, "WARM", "Standard", 0,
     "Why this lead — Mahindra Electric (Body/Chassis Welding Line)\n\n"
     "• 28 May 2026 — LAND_ACQUISITION (Tier 2): MIDC plot allotment at "
     "Chakan.\n",
     [("Deepa Iyer", "Procurement Lead", "deepa.iyer@mahindra.com", "Low")]),

    (6, "Amara Raja Energy Ltd", "L31402AP1985PLC000006", "Tirupati, Andhra Pradesh",
     APP_PACK, 18.9, "COLD", "Value", 0,
     "Why this lead — Amara Raja Energy (Battery Pack Assembly)\n\n"
     "• 22 May 2026 — NEWS_MENTION (Tier 3): press note mentions gigafactory "
     "intent; no hard CAPEX yet.\n\n"
     "Score reduced 0.3x — a competitor is locked in for this application "
     "(see competitor intel).",
     []),
]

# Real raw_signals per company → drives the lead card's signal timeline.
# (signal_type, days_ago, snippet)
SIGNALS: dict[int, list[tuple[str, int, str]]] = {
    1: [("CAPEX_FILING", 10, "BSE filing: ₹650cr expansion for a new cell line in Hosur"),
        ("LAND_ACQUISITION", 4, "40-acre SIPCOT allotment adjacent to existing plant"),
        ("JOB_POSTING", 2, "14 openings for cell-line process engineers, Hosur")],
    2: [("PLI_APPROVAL", 17, "Listed in the ACC battery PLI beneficiary update"),
        ("EC_CLEARANCE", 8, "Environmental clearance for a lithium-cell unit, Karnataka")],
    3: [("ICEGATE_IMPORT", 12, "Import of pack-assembly machinery (HS 8479), Chennai port"),
        ("OEM_CONTRACT_WIN", 6, "Announced in-house battery pack line ramp-up")],
    4: [("CAPEX_FILING", 20, "Board approves EV body-shop modernisation at Pune"),
        ("JOB_POSTING", 3, "Welding-line automation engineer roles posted")],
    5: [("LAND_ACQUISITION", 25, "MIDC industrial plot allotment at Chakan")],
    6: [("NEWS_MENTION", 31, "Press note mentions gigafactory intent; no hard CAPEX yet")],
}

# Competitor intelligence per company (brand, evidence, days_ago, confidence, move).
COMPETITORS: dict[int, list[tuple[str, str, int, str, str]]] = {
    1: [("Manz AG", "Tender specification mention", 15, "Low",
         "Emphasise India-based commissioning + faster spares support")],
    3: [("Hitachi High-Tech", "Existing line supplier", 40, "Medium",
         "Position on lead-time and local service vs. imported support")],
    6: [("Wuxi Lead", "Locked-in multi-year contract", 20, "High",
         "De-prioritise — category is locked for this cycle")],
}

# Negative-signal flags (company_n → (flag_label, multiplier)) — score transparency.
NEGATIVE: dict[int, tuple[str, float]] = {
    6: ("COMPETITOR_LOCKED_IN", 0.3),
}


def seed() -> None:
    with get_cursor() as cur:
        # --- reference: category + applications --------------------------------
        cur.execute(
            """
            INSERT INTO vendor_categories (id, industry_id, category_name, category_type)
            VALUES (%s, %s, 'Battery & Body Line Equipment', 'Equipment')
            ON CONFLICT (id) DO NOTHING
            """,
            (CATEGORY_ID, INDUSTRY_ID),
        )
        for app_id, name, line in [
            (APP_CELL, "Battery Cell Assembly Line", "Battery Line"),
            (APP_PACK, "Battery Pack Assembly", "Battery Line"),
            (APP_BODY, "Body/Chassis Welding Line", "Body/Chassis Line"),
        ]:
            cur.execute(
                """
                INSERT INTO applications
                  (id, category_id, application_name, production_line_type, typical_price_tier)
                VALUES (%s, %s, %s, %s, 'Both')
                ON CONFLICT (id) DO NOTHING
                """,
                (app_id, CATEGORY_ID, name, line),
            )

        # --- demo vendor -------------------------------------------------------
        cur.execute(
            """
            INSERT INTO vendors
              (id, vendor_name, industry_id, application_id, price_tier,
               geography, min_deal_size_inr, onboarding_complete, api_key)
            VALUES (%s, 'Demo Equipment Co', %s, %s, 'Premium',
                    %s, 5000000, TRUE, %s)
            ON CONFLICT (id) DO UPDATE SET api_key = EXCLUDED.api_key
            """,
            (VENDOR_ID, INDUSTRY_ID, APP_CELL,
             ["Maharashtra", "Tamil Nadu", "Karnataka", "Andhra Pradesh"],
             DEMO_API_KEY),
        )

        # --- companies, scores, contacts, deliveries ---------------------------
        for (n, legal, cin, loc, app_id, score, status, tier, excl_h,
             why, contacts) in DEMO:
            cid = _company_uuid(n)
            sid = _score_uuid(n)
            did = _delivery_uuid(n)

            neg_flag, neg_mult = NEGATIVE.get(n, ("None", 1.0))
            cur.execute(
                """
                INSERT INTO companies (id, industry_id, legal_name, cin,
                                       plant_location, negative_flag, negative_flag_date)
                VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s <> 'None'
                        THEN CURRENT_DATE ELSE NULL END)
                ON CONFLICT (id) DO UPDATE
                  SET negative_flag = EXCLUDED.negative_flag,
                      negative_flag_date = EXCLUDED.negative_flag_date
                """,
                (cid, INDUSTRY_ID, legal, cin, loc, neg_flag, neg_flag),
            )

            # Real raw_signals so the lead card's timeline is populated.
            for sig_type, days_ago, snippet in SIGNALS.get(n, []):
                cur.execute(
                    """
                    INSERT INTO raw_signals
                      (signal_id, industry_id, date_detected, signal_type,
                       raw_company_name, resolved_company_id, entity_confidence_pct,
                       resolution_tier, source, source_url, raw_text_snippet,
                       application_tags)
                    VALUES (%s, %s, CURRENT_DATE - %s, %s, %s, %s, 100, 'A',
                            'DemoSeed', %s, %s, %s::uuid[])
                    ON CONFLICT (signal_id) DO NOTHING
                    """,
                    (f"SIG-DEMO-{n}-{sig_type}", INDUSTRY_ID, days_ago, sig_type,
                     legal, cid, f"https://demo.forgeiq/{sig_type.lower()}",
                     snippet, [app_id]),
                )

            # Competitor intelligence for the lead card.
            for brand, ev_type, days_ago, conf, move in COMPETITORS.get(n, []):
                cur.execute(
                    """
                    INSERT INTO competitor_intelligence
                      (company_id, application_id, competitor_brand, evidence_type,
                       evidence_date, confidence, recommended_move)
                    SELECT %s, %s, %s, %s, CURRENT_DATE - %s, %s, %s
                    WHERE NOT EXISTS (
                      SELECT 1 FROM competitor_intelligence
                      WHERE company_id = %s AND competitor_brand = %s)
                    """,
                    (cid, app_id, brand, ev_type, days_ago, conf, move,
                     cid, brand),
                )

            cur.execute(
                """
                INSERT INTO scores
                  (id, company_id, application_id, current_score, status,
                   negative_multiplier, last_calculated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (company_id, application_id) DO UPDATE
                  SET current_score = EXCLUDED.current_score,
                      status = EXCLUDED.status,
                      negative_multiplier = EXCLUDED.negative_multiplier,
                      last_calculated_at = EXCLUDED.last_calculated_at
                """,
                (sid, cid, app_id, score, status, neg_mult, now),
            )

            contact_ids = []
            for ci, (cname, role, email, ctier) in enumerate(contacts):
                contact_uuid = _contact_uuid(n * 10 + ci)
                cur.execute(
                    """
                    INSERT INTO contacts
                      (id, company_id, full_name, role, confidence_tier,
                       email_pattern_guess, source)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Demo')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (contact_uuid, cid, cname, role, ctier, email),
                )
                contact_ids.append(contact_uuid)

            excl_end = now + timedelta(hours=excl_h) if excl_h else None
            cur.execute(
                """
                INSERT INTO lead_delivery
                  (id, score_id, vendor_id, delivered_at, exclusivity_window_end,
                   confidence_tier_shown, contact_ids, why_explanation,
                   human_spotcheck_done)
                VALUES (%s, %s, %s, %s, %s, %s, %s::uuid[], %s, TRUE)
                ON CONFLICT (id) DO UPDATE
                  SET why_explanation = EXCLUDED.why_explanation,
                      exclusivity_window_end = EXCLUDED.exclusivity_window_end,
                      contact_ids = EXCLUDED.contact_ids
                """,
                (did, sid, VENDOR_ID, now - timedelta(days=n),
                 excl_end, tier, contact_ids or None, why),
            )

    print("Demo data seeded.")
    print(f"  Applications: 3   Companies: {len(DEMO)}   "
          f"Leads delivered to demo vendor: {len(DEMO)}")
    print()
    print("  Log into the dashboard with this API key:")
    print(f"    {DEMO_API_KEY}")


if __name__ == "__main__":
    seed()
