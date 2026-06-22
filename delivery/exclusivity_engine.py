"""Exclusivity window engine.

Controls how many vendors may receive the same HOT lead and enforces a
head-start for higher tiers. Pricing config per tier:

  tier      max_vendors   head_start_hours
  Premium   1             72
  Standard  2             48
  Value     3             24

get_available_exclusivity_slots() returns how many vendors may still be served
the lead right now (0 means either the cap is reached or a head-start window is
still running).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from db.connection import fetch_all

# Pricing config — in production this can live in a pricing_config table.
PRICING = {
    "Premium":  {"exclusivity_max_vendors": 1, "head_start_hours": 72},
    "Standard": {"exclusivity_max_vendors": 2, "head_start_hours": 48},
    "Value":    {"exclusivity_max_vendors": 3, "head_start_hours": 24},
}
DEFAULT_PRICING = {"exclusivity_max_vendors": 2, "head_start_hours": 48}


def get_pricing_config(price_tier: str) -> dict:
    return PRICING.get(price_tier, DEFAULT_PRICING)


def _deliveries_for_score(score_id: str) -> list[dict]:
    return fetch_all(
        "SELECT delivered_at FROM lead_delivery WHERE score_id = %s "
        "ORDER BY delivered_at ASC", (score_id,))


def get_available_exclusivity_slots(score_id: str, vendor) -> int:
    """Return the number of vendors that may still receive this lead now."""
    pricing = get_pricing_config(
        vendor["price_tier"] if isinstance(vendor, dict) else vendor.price_tier)
    max_vendors = pricing["exclusivity_max_vendors"]
    head_start = pricing["head_start_hours"]

    existing = _deliveries_for_score(score_id)
    if len(existing) >= max_vendors:
        return 0

    # If a head-start delivery exists, the window must elapse before the next
    # vendor can be served.
    if existing:
        first = existing[0]["delivered_at"]
        window_end = first + timedelta(hours=head_start)
        now = datetime.now(timezone.utc) if first.tzinfo else datetime.now()
        if now < window_end:
            return 0

    return max_vendors - len(existing)


if __name__ == "__main__":
    # Offline: verify slot math with stubbed delivery history.
    import delivery.exclusivity_engine as m
    now = datetime.now()

    premium = {"price_tier": "Premium"}
    value = {"price_tier": "Value"}

    # Premium, no deliveries -> exactly 1 slot.
    m._deliveries_for_score = lambda sid: []
    assert m.get_available_exclusivity_slots("s1", premium) == 1

    # Premium already delivered once -> capped at 0.
    m._deliveries_for_score = lambda sid: [{"delivered_at": now}]
    assert m.get_available_exclusivity_slots("s1", premium) == 0

    # Value, one delivery 1h ago -> still inside 24h head-start -> 0.
    m._deliveries_for_score = lambda sid: [
        {"delivered_at": now - timedelta(hours=1)}]
    assert m.get_available_exclusivity_slots("s1", value) == 0

    # Value, one delivery 30h ago -> head-start elapsed -> 2 remaining of 3.
    m._deliveries_for_score = lambda sid: [
        {"delivered_at": now - timedelta(hours=30)}]
    assert m.get_available_exclusivity_slots("s1", value) == 2
    print("OK: exclusivity caps + head-start windows enforced per tier.")
