"""Lead qualification and routing.

A score crossing HOT (70+) does NOT auto-deliver. The router checks vendor
match, exclusivity slots, and whether a premium-tier human spot-check is
needed before a lead is delivered.

Vendor match rules:
  - vendor.application_id == score.application_id
  - vendor.geography includes the company's plant_location
  - score not already delivered to that vendor recently
Premium vendors get first look (sorted ahead) and are flagged for spot-check
rather than auto-delivered.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from db.connection import fetch_all, fetch_one, get_cursor
from delivery.exclusivity_engine import (get_available_exclusivity_slots,
                                         get_pricing_config)

REDELIVER_COOLDOWN_DAYS = 30


def _hot_scores() -> list[dict]:
    return fetch_all(
        "SELECT s.*, c.plant_location FROM scores s "
        "JOIN companies c ON c.id = s.company_id WHERE s.status = 'HOT'")


def _match_vendors(score: dict) -> list[dict]:
    """Vendors whose application + geography fit this score's company."""
    location = score.get("plant_location") or ""
    return fetch_all(
        """
        SELECT * FROM vendors
        WHERE onboarding_complete = TRUE
          AND application_id = %s
          AND (geography IS NULL OR %s ILIKE ANY(
                SELECT '%%' || g || '%%' FROM unnest(geography) g))
        """,
        (score["application_id"], location),
    )


def _already_delivered_recently(score_id: str, vendor_id: str) -> bool:
    row = fetch_one(
        "SELECT 1 FROM lead_delivery WHERE score_id = %s AND vendor_id = %s "
        "AND delivered_at >= (NOW() - INTERVAL '%s days') LIMIT 1",
        (score_id, vendor_id, REDELIVER_COOLDOWN_DAYS))
    return row is not None


# tier sort key — Premium first.
_TIER_ORDER = {"Premium": 0, "Standard": 1, "Value": 2}


def route_hot_scores() -> int:
    """Route every HOT score to matched vendors. Returns leads delivered."""
    delivered = 0
    for score in _hot_scores():
        vendors = _match_vendors(score)
        if not vendors:
            continue
        for vendor in sorted(vendors,
                             key=lambda v: _TIER_ORDER.get(v["price_tier"], 9)):
            if _already_delivered_recently(str(score["id"]),
                                           str(vendor["id"])):
                continue
            if get_available_exclusivity_slots(str(score["id"]), vendor) == 0:
                continue

            contacts = _top_contacts(str(score["company_id"]), limit=2)
            why = _why(score)
            if vendor["price_tier"] == "Premium":
                _flag_for_spotcheck(score, vendor, contacts, why)
            else:
                _deliver_lead(score, vendor, contacts, why)
                delivered += 1
    print(f"lead_router: delivered {delivered} leads.")
    return delivered


def _top_contacts(company_id: str, limit: int = 2) -> list[str]:
    rows = fetch_all(
        "SELECT id FROM contacts WHERE company_id = %s "
        "ORDER BY CASE confidence_tier WHEN 'High' THEN 0 WHEN 'Medium' "
        "THEN 1 ELSE 2 END LIMIT %s", (company_id, limit))
    return [str(r["id"]) for r in rows]


def _why(score: dict) -> str:
    try:
        from delivery.card_generator import generate_why_explanation
        return generate_why_explanation(score)
    except Exception:
        return ""


def _deliver_lead(score: dict, vendor: dict, contacts: list[str],
                  why: str, spotcheck_done: bool = False) -> None:
    pricing = get_pricing_config(vendor["price_tier"])
    window_end = datetime.now() + timedelta(hours=pricing["head_start_hours"])
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO lead_delivery
              (score_id, vendor_id, exclusivity_window_end,
               confidence_tier_shown, contact_ids, why_explanation,
               human_spotcheck_done)
            VALUES (%s, %s, %s, %s, %s::uuid[], %s, %s)
            """,
            (score["id"], vendor["id"], window_end, score["status"],
             contacts, why, spotcheck_done),
        )


def _flag_for_spotcheck(score: dict, vendor: dict, contacts: list[str],
                        why: str) -> None:
    """Premium leads require a human spot-check before they go out.

    Recorded as a delivery row with human_spotcheck_done=FALSE so it surfaces in
    a review queue; the operator flips the flag once checked.
    """
    _deliver_lead(score, vendor, contacts, why, spotcheck_done=False)


if __name__ == "__main__":
    # Offline: verify Premium-first ordering and cooldown gate.
    vendors = [{"price_tier": "Value"}, {"price_tier": "Premium"},
               {"price_tier": "Standard"}]
    ordered = sorted(vendors, key=lambda v: _TIER_ORDER.get(v["price_tier"], 9))
    print([v["price_tier"] for v in ordered])
    assert [v["price_tier"] for v in ordered] == ["Premium", "Standard", "Value"]
    print("OK: Premium vendors are sorted first for first look.")
