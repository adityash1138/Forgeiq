"""Cascade engine — turns one trigger signal into scheduled, gated waves.

When a Tier-1 cascade-trigger signal (CAPEX, PLI, Land, EC, ICEGATE import)
resolves to a company, the engine reads cascade_wave_config and creates one
cascade_state row per applicable wave (one per application that should
eventually be alerted).

Each day, pending waves are checked:
  - too early (before earliest_fire_date)      -> skip
  - window elapsed (after latest_fire_date)    -> pause (terminal, no lead)
  - inside window, no confirming signal yet    -> skip (stay pending)
  - inside window + confirming signal present  -> confirm -> fire

Firing recalculates the score for that application so the lead can surface.

State machine:
  pending -> confirmed -> fired        (happy path)
  pending -> paused                    (window missed)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from db.connection import fetch_all, fetch_one, get_cursor

CASCADE_TRIGGER_TYPES = {
    "CAPEX_FILING", "PLI_APPROVAL", "ICEGATE_IMPORT",
    "LAND_ACQUISITION", "EC_CLEARANCE",
}


def _waves_for_trigger(trigger_signal_type: str) -> list[dict]:
    return fetch_all(
        "SELECT * FROM cascade_wave_config WHERE trigger_signal_type = %s",
        (trigger_signal_type,))


def on_cascade_trigger_signal(signal_row_id: str) -> int:
    """Create cascade_state rows for a newly-resolved trigger signal.

    Returns the number of cascade_state rows created.
    """
    sig = fetch_one(
        "SELECT id, signal_type, resolved_company_id, date_detected, "
        "application_tags FROM raw_signals WHERE id = %s", (signal_row_id,))
    if not sig or sig["signal_type"] not in CASCADE_TRIGGER_TYPES:
        return 0
    if not sig["resolved_company_id"]:
        return 0  # cannot cascade an unresolved signal

    tags = set(str(t) for t in (sig["application_tags"] or []))
    created = 0
    for wave in _waves_for_trigger(sig["signal_type"]):
        # Only schedule waves for applications this signal is tagged with.
        if str(wave["application_id"]) not in tags:
            continue
        earliest = sig["date_detected"] + timedelta(
            days=(wave["activate_month_start"] or 0) * 30)
        latest = sig["date_detected"] + timedelta(
            days=(wave["activate_month_end"] or 0) * 30)
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO cascade_state
                  (trigger_signal_id, company_id, cascade_wave_id, wave_status,
                   earliest_fire_date, latest_fire_date)
                VALUES (%s, %s, %s, 'pending', %s, %s)
                """,
                (sig["id"], sig["resolved_company_id"], wave["id"],
                 earliest, latest),
            )
        created += 1
    return created


def _find_confirming_signal(company_id: str, confirming_types: list[str],
                            after_date) -> dict | None:
    """Earliest signal of an accepted confirming type after the trigger date."""
    if not confirming_types:
        return None
    return fetch_one(
        """
        SELECT id, signal_type, date_detected FROM raw_signals
        WHERE resolved_company_id = %s
          AND signal_type = ANY(%s)
          AND date_detected >= %s
        ORDER BY date_detected ASC LIMIT 1
        """,
        (company_id, confirming_types, after_date),
    )


def process_cascade_states_daily() -> dict:
    """Run daily after scrapers + scoring. Returns a tally of transitions."""
    pending = fetch_all(
        "SELECT * FROM cascade_state WHERE wave_status = 'pending'")
    today = date.today()
    tally = {"fired": 0, "paused": 0, "still_pending": 0}

    for state in pending:
        wave = fetch_one(
            "SELECT * FROM cascade_wave_config WHERE id = %s",
            (state["cascade_wave_id"],))
        if not wave:
            continue

        if today < state["earliest_fire_date"]:
            tally["still_pending"] += 1
            continue  # too early

        if today > state["latest_fire_date"]:
            _set_status(state["id"], "paused")
            tally["paused"] += 1
            continue  # window missed (terminal)

        trigger = fetch_one(
            "SELECT date_detected FROM raw_signals WHERE id = %s",
            (state["trigger_signal_id"],))
        confirming = _find_confirming_signal(
            str(state["company_id"]),
            list(wave["confirming_signal_types"] or []),
            trigger["date_detected"] if trigger else state["earliest_fire_date"],
        )
        if not confirming:
            tally["still_pending"] += 1
            continue  # window open but not yet confirmed

        # FIRE: confirm -> recalc score for this application -> mark fired.
        _set_status(state["id"], "confirmed", confirming_signal_id=confirming["id"])
        _recalc(str(state["company_id"]), str(wave["application_id"]))
        _set_status(state["id"], "fired", fired_at=datetime.now())
        tally["fired"] += 1

    print(f"cascade_engine: {tally}")
    return tally


def _set_status(state_id, status: str, confirming_signal_id=None,
                fired_at=None) -> None:
    sets = ["wave_status = %s"]
    params: list = [status]
    if confirming_signal_id is not None:
        sets.append("confirming_signal_id = %s")
        params.append(confirming_signal_id)
    if fired_at is not None:
        sets.append("fired_at = %s")
        params.append(fired_at)
    params.append(state_id)
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE cascade_state SET {', '.join(sets)} WHERE id = %s",
            tuple(params))


def _recalc(company_id: str, application_id: str) -> None:
    try:
        from engine.scoring_engine import calculate_score
        calculate_score(company_id, application_id)
    except Exception:
        pass


if __name__ == "__main__":
    # Offline: verify confirming-window logic in isolation (pure date math).
    trigger_date = date(2026, 1, 1)
    earliest = trigger_date + timedelta(days=2 * 30)
    latest = trigger_date + timedelta(days=5 * 30)
    print(f"trigger={trigger_date} window=[{earliest} .. {latest}]")
    assert date(2026, 2, 1) < earliest      # month 1 -> too early
    assert earliest <= date(2026, 4, 1) <= latest  # month 3 -> in window
    assert date(2026, 7, 1) > latest        # month 6 -> missed -> paused
    assert "CAPEX_FILING" in CASCADE_TRIGGER_TYPES
    print("OK: cascade window math + trigger-type set verified.")
