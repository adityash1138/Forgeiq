"""The master scoring engine — the most important file in the codebase.

Score formula (per Company x Application):

    raw   = SUM(base_strength x tier_weight x decay_position) over linked signals
    norm  = min(raw / MAX_POSSIBLE * 100, 100)
    final = round(norm x negative_multiplier, 2)

    status = HOT (>=70) | WARM (>=40) | COLD (<40)

A signal is "linked" to a Company x Application when it resolved to the company
AND its application_tags include the application.
"""
from __future__ import annotations

from datetime import date, datetime

from db.connection import fetch_all, get_cursor
from engine.decay_calculator import calculate_decay_position
from engine.negative_handler import get_negative_multiplier

# Tune from real data once enough signals accumulate. Sets the raw score that
# maps to a normalized 100.
MAX_POSSIBLE = 35.0


def _signals_for_company_app(company_id: str, application_id: str) -> list[dict]:
    """Resolved signals for this company whose tags include this application."""
    return fetch_all(
        """
        SELECT rs.id, rs.signal_type, rs.date_detected,
               c.base_strength, c.tier_weight,
               c.decay_curve, c.peak_start_days, c.peak_end_days,
               c.total_decay_days
        FROM raw_signals rs
        JOIN signal_type_config c ON c.signal_type = rs.signal_type
        WHERE rs.resolved_company_id = %s
          AND %s = ANY(rs.application_tags)
        """,
        (company_id, application_id),
    )


def calculate_score(company_id: str, application_id: str) -> float:
    """Compute, persist, and return the score for one Company x Application."""
    signals = _signals_for_company_app(company_id, application_id)
    raw_score = 0.0
    contributing: list[str] = []

    for sig in signals:
        days_elapsed = (date.today() - sig["date_detected"]).days
        decay = calculate_decay_position(sig, days_elapsed)
        contribution = (sig["base_strength"] or 0) * \
            float(sig["tier_weight"] or 0) * decay
        raw_score += contribution
        contributing.append(str(sig["id"]))

    normalized = min((raw_score / MAX_POSSIBLE) * 100, 100)
    multiplier = get_negative_multiplier(company_id, application_id)
    final_score = round(normalized * multiplier, 2)
    status = "HOT" if final_score >= 70 else "WARM" if final_score >= 40 else "COLD"

    _upsert_score(company_id, application_id, final_score, status,
                  multiplier, contributing)
    return final_score


def _upsert_score(company_id: str, application_id: str, score: float,
                  status: str, multiplier: float,
                  contributing: list[str]) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO scores
              (company_id, application_id, current_score, status,
               negative_multiplier, contributing_signal_ids, last_calculated_at)
            VALUES (%s, %s, %s, %s, %s, %s::uuid[], %s)
            ON CONFLICT (company_id, application_id) DO UPDATE SET
              current_score = EXCLUDED.current_score,
              status = EXCLUDED.status,
              negative_multiplier = EXCLUDED.negative_multiplier,
              contributing_signal_ids = EXCLUDED.contributing_signal_ids,
              last_calculated_at = EXCLUDED.last_calculated_at
            """,
            (company_id, application_id, score, status, multiplier,
             contributing, datetime.now()),
        )


def recalculate_company(company_id: str) -> int:
    """Recalculate every application score for one company.

    Triggered immediately when a new signal resolves to the company (Tier A/B).
    Recomputes only applications that actually have a linked signal.
    """
    apps = fetch_all(
        """
        SELECT DISTINCT unnest(application_tags) AS application_id
        FROM raw_signals
        WHERE resolved_company_id = %s AND application_tags IS NOT NULL
        """,
        (company_id,),
    )
    for a in apps:
        if a["application_id"]:
            calculate_score(company_id, str(a["application_id"]))
    return len(apps)


def recalculate_all_due() -> int:
    """Daily pass: recompute scores for every company with resolved signals.

    Cheaper-than-it-looks because the per-company query only touches applications
    that have linked signals. In production this can be narrowed to companies
    whose signals crossed a peak/total boundary today; for the MVP we recompute
    all so no stale score ever lingers.
    """
    companies = fetch_all(
        "SELECT DISTINCT resolved_company_id AS cid FROM raw_signals "
        "WHERE resolved_company_id IS NOT NULL")
    total = 0
    for c in companies:
        total += recalculate_company(str(c["cid"]))
    print(f"scoring_engine: recalculated {total} company-application scores "
          f"across {len(companies)} companies.")
    return total


if __name__ == "__main__":
    # Offline: verify the formula end-to-end with stubbed signal data, no DB.
    import engine.scoring_engine as m

    today = date.today()
    # One Tier-1 CAPEX (Wave, str 10, weight 1.0) at peak + one Tier-3 news.
    m._signals_for_company_app = lambda cid, aid: [
        {"id": "s1", "signal_type": "CAPEX_FILING", "date_detected": today,
         "base_strength": 10, "tier_weight": 1.0, "decay_curve": "Wave",
         "peak_start_days": 0, "peak_end_days": 270, "total_decay_days": 540},
        {"id": "s2", "signal_type": "NEWS_MENTION", "date_detected": today,
         "base_strength": 3, "tier_weight": 0.25, "decay_curve": "Cliff",
         "peak_start_days": 0, "peak_end_days": 30, "total_decay_days": 90},
    ]
    m.get_negative_multiplier = lambda cid, aid: 1.0
    captured = {}
    m._upsert_score = lambda *a: captured.update(
        dict(zip(["cid", "aid", "score", "status", "mult", "contrib"], a)))

    # raw = 10*1.0*1.0 + 3*0.25*1.0 = 10.75 ; norm = 10.75/35*100 = 30.71
    score = m.calculate_score("c1", "APP-001")
    print(f"score={score} status={captured['status']} "
          f"contrib={captured['contrib']}")
    assert abs(score - 30.71) < 0.05
    assert captured["status"] == "COLD"

    # With a Class-2 negative the same raw collapses to 0.1x -> ~3.07.
    m.get_negative_multiplier = lambda cid, aid: 0.1
    assert abs(m.calculate_score("c1", "APP-001") - 3.07) < 0.05
    print("OK: scoring formula, normalisation, and negative multiplier verified.")
