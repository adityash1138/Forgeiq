"""Negative signal handler — 3 severity classes.

Computes the multiplier applied to a Company x Application score:

  Class1_Existential     -> 0.0  (zero out everything, full stop)
  Class2_Heavy           -> 0.1  (company-wide, regardless of application)
  Class3_CategorySpecific-> 0.3  (ONLY if the negative targets this application)

Class 2 negatives auto-recover 90 days after they were flagged; recovered
negatives no longer suppress the score.
"""
from __future__ import annotations

from datetime import date

from db.connection import fetch_all, fetch_one


def _active_negatives(company_id: str) -> list[dict]:
    """Active negative flags for a company, joined to their config.

    A negative is recorded on the companies row (negative_flag, _date, _notes).
    Class 2 negatives that auto-recover are filtered out once 90 days elapse.
    """
    company = fetch_one(
        "SELECT negative_flag, negative_flag_date, negative_flag_notes "
        "FROM companies WHERE id = %s", (company_id,))
    if not company or not company["negative_flag"] \
            or company["negative_flag"] == "None":
        return []

    config = fetch_one(
        "SELECT * FROM negative_signals_config WHERE negative_signal_type = %s",
        (company["negative_flag"],))
    if not config:
        return []

    # Auto-recovery: Class 2 (90-day) negatives expire.
    if config["auto_recovers"] and config["recovery_trigger"] == "90_days_elapsed":
        flagged = company["negative_flag_date"]
        if flagged and (date.today() - flagged).days >= 90:
            return []

    # negative_flag_notes may carry the application_id a Class 3 negative targets.
    return [{
        "negative_signal_type": company["negative_flag"],
        "severity_class": config["severity_class"],
        "application_id": company["negative_flag_notes"],  # app UUID or None
    }]


def get_negative_multiplier(company_id: str, application_id: str) -> float:
    """Return the multiplier (0.0-1.0) for this Company x Application."""
    for neg in _active_negatives(company_id):
        sev = neg["severity_class"]
        if sev == "Class1_Existential":
            return 0.0
        if sev == "Class2_Heavy":
            return 0.1
        if sev == "Class3_CategorySpecific":
            # Only suppress if this negative targets this specific application.
            if neg.get("application_id") == application_id:
                return 0.3
    return 1.0  # no active negative — full score


if __name__ == "__main__":
    # Offline: verify class logic with stubbed _active_negatives.
    import engine.negative_handler as m

    m._active_negatives = lambda cid: [
        {"severity_class": "Class3_CategorySpecific", "application_id": "APP-001"}
    ]
    assert m.get_negative_multiplier("c1", "APP-001") == 0.3  # targeted app
    assert m.get_negative_multiplier("c1", "APP-002") == 1.0  # other app safe

    m._active_negatives = lambda cid: [{"severity_class": "Class2_Heavy"}]
    assert m.get_negative_multiplier("c1", "APP-001") == 0.1
    assert m.get_negative_multiplier("c1", "APP-002") == 0.1  # company-wide

    m._active_negatives = lambda cid: [{"severity_class": "Class1_Existential"}]
    assert m.get_negative_multiplier("c1", "ANY") == 0.0

    m._active_negatives = lambda cid: []
    assert m.get_negative_multiplier("c1", "ANY") == 1.0
    print("OK: Class 1 zeroes all, Class 2 hits all apps, "
          "Class 3 hits only its target app.")
