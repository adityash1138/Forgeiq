"""Outcome capture + feedback loop.

Records vendor/buyer outcomes and watches for systematic failure patterns that
warrant a founder config review. For the first 6 months config adjustment is
manual (the founder hand-edits signal_type_config / cascade_wave_config from the
outcomes table); this module only captures data and raises review flags — it
does NOT auto-tune weights until 50+ outcomes exist.
"""
from __future__ import annotations

from db.connection import fetch_all, fetch_one, get_cursor

# Outcome statuses we treat as "negative" for pattern detection.
NEGATIVE_STATUSES = {"No response", "Lost-Competitor", "Not-Relevant",
                     "Lost-Timing too early"}
SYSTEMATIC_THRESHOLD = 5  # repeats of the same negative status -> flag
MIN_OUTCOMES_FOR_TUNING = 50


def record_outcome(delivery_id: str, outcome_status: str,
                   reason: str | None = None,
                   captured_via: str = "app") -> str:
    """Insert an outcome row, then check for systematic-failure patterns.

    Returns the new outcome's UUID.
    """
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO outcomes "
            "(delivery_id, outcome_status, reason_detail, captured_via) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (delivery_id, outcome_status, reason, captured_via))
        outcome_id = str(cur.fetchone()["id"])

    check_for_systematic_failures(outcome_status)
    return outcome_id


def check_for_systematic_failures(outcome_status: str) -> bool:
    """Flag for founder review when one negative status repeats enough times.

    Returns True if a review flag was raised. No auto-tuning happens here.
    """
    if outcome_status not in NEGATIVE_STATUSES:
        return False
    row = fetch_one(
        "SELECT COUNT(*) AS n FROM outcomes WHERE outcome_status = %s",
        (outcome_status,))
    count = row["n"] if row else 0
    if count and count % SYSTEMATIC_THRESHOLD == 0:
        print(f"[CONFIG REVIEW] '{outcome_status}' has occurred {count} times. "
              "Founder should review the relevant config table — see blueprint "
              "I2 outcome->config mapping. (No auto-tuning until "
              f"{MIN_OUTCOMES_FOR_TUNING}+ outcomes.)")
        return True
    return False


def send_14day_pings() -> int:
    """Find deliveries that are 14 days old with no outcome and queue a ping.

    Returns the count of pings that would be sent. Actual WhatsApp dispatch is
    handled by the messaging integration (Twilio / WA Business API); here we
    select the targets so the scheduler can fire them.
    """
    due = fetch_all(
        """
        SELECT ld.id AS delivery_id, v.vendor_name
        FROM lead_delivery ld
        JOIN vendors v ON v.id = ld.vendor_id
        LEFT JOIN outcomes o ON o.delivery_id = ld.id
        WHERE o.id IS NULL
          AND ld.delivered_at <= (NOW() - INTERVAL '14 days')
        """)
    for d in due:
        _dispatch_ping(str(d["delivery_id"]))
    print(f"outcome_processor: queued {len(due)} 14-day feedback pings.")
    return len(due)


def _dispatch_ping(delivery_id: str) -> None:
    """Hook for the WhatsApp messaging integration. No-op without credentials."""
    # Wire Twilio / WA Business API here using ALERT_WHATSAPP_NUMBER etc.
    pass


if __name__ == "__main__":
    # Offline: verify the systematic-failure flag fires on the Nth negative.
    import feedback.outcome_processor as m

    counter = {"n": 0}

    def fake_fetch_one(q, params):
        counter["n"] += 1
        return {"n": counter["n"]}

    m.fetch_one = fake_fetch_one
    flags = [m.check_for_systematic_failures("Lost-Competitor")
             for _ in range(5)]
    print(f"flag pattern over 5 identical negatives: {flags}")
    assert flags == [False, False, False, False, True]  # flags on the 5th
    assert m.check_for_systematic_failures("Won") is False  # positive ignored
    print("OK: systematic-failure flag fires every Nth negative; positives "
          "ignored.")
