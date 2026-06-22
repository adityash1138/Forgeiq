"""Lead Card generation — the why-explanation.

Builds the human-readable justification shown on a lead card: a dated timeline
of contributing signals, a note if a negative multiplier was applied, and any
competitor-intelligence recommendation.
"""
from __future__ import annotations

from db.connection import fetch_all, fetch_one

# Human labels for signal types shown on the card.
SIGNAL_HUMAN_LABELS = {
    "GEM_TENDER": "GeM tender",
    "CAPEX_FILING": "CAPEX filing",
    "PLI_APPROVAL": "PLI approval",
    "ICEGATE_IMPORT": "Import shipment",
    "JOB_POSTING": "Hiring",
    "LAND_ACQUISITION": "Land acquisition",
    "EC_CLEARANCE": "Environmental clearance",
    "OEM_CONTRACT_WIN": "OEM contract win",
    "VC_PE_FUNDING": "Funding round",
    "MCA_ROC_FILING": "MCA/ROC filing",
    "GST_NEW_STATE": "New GST registration",
    "LINKEDIN_ACTIVITY": "LinkedIn activity",
    "NEWS_MENTION": "News mention",
}


def _signals_by_ids(signal_ids: list) -> list[dict]:
    if not signal_ids:
        return []
    return fetch_all(
        "SELECT id, signal_type, date_detected, raw_text_snippet "
        "FROM raw_signals WHERE id = ANY(%s::uuid[]) ORDER BY date_detected ASC",
        (signal_ids,))


def generate_why_explanation(score) -> str:
    """Compose the why-explanation string for a score row (dict or record)."""
    get = (lambda k: score[k]) if isinstance(score, dict) else \
        (lambda k: getattr(score, k))

    signals = _signals_by_ids(get("contributing_signal_ids") or [])
    parts: list[str] = []
    for sig in signals:
        label = SIGNAL_HUMAN_LABELS.get(sig["signal_type"], sig["signal_type"])
        snippet = (sig["raw_text_snippet"] or "")[:120]
        parts.append(f"{sig['date_detected']:%b %d} — {label}: {snippet}")

    # Negative-signal adjustment note.
    multiplier = get("negative_multiplier")
    if multiplier is not None and float(multiplier) < 1.0:
        current = float(get("current_score") or 0)
        pre = round(current / float(multiplier), 0) if float(multiplier) else current
        parts.append(
            f"Score adjusted {pre:.0f}->{current:.0f} due to competitor/"
            "negative signal")

    # Competitor intel, if any.
    intel = fetch_one(
        "SELECT recommended_move FROM competitor_intelligence "
        "WHERE company_id = %s AND application_id = %s LIMIT 1",
        (get("company_id"), get("application_id")))
    if intel and intel["recommended_move"]:
        parts.append(f"Competitor note: {intel['recommended_move']}")

    return "\n".join(parts)


if __name__ == "__main__":
    # Offline: verify timeline + negative-adjustment composition, no DB.
    import datetime as dt
    import delivery.card_generator as m

    m._signals_by_ids = lambda ids: [
        {"signal_type": "CAPEX_FILING", "date_detected": dt.date(2026, 1, 15),
         "raw_text_snippet": "Rs 9500 cr greenfield battery plant"},
        {"signal_type": "JOB_POSTING", "date_detected": dt.date(2026, 3, 2),
         "raw_text_snippet": "Hiring Plant Head, Battery Pack Assembly"},
    ]
    m.fetch_one = lambda *a, **k: None
    score = {"contributing_signal_ids": ["s1", "s2"], "negative_multiplier": 0.3,
             "current_score": 21.0, "company_id": "c1", "application_id": "a1"}
    why = m.generate_why_explanation(score)
    print(why)
    assert "CAPEX filing" in why and "Hiring" in why
    assert "70->21" in why  # 21 / 0.3 = 70 pre-suppression
    print("OK: why-explanation timeline + negative-adjustment note built.")
