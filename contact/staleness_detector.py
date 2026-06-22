"""Contact staleness detection and confidence scoring.

Confidence tiers gate how a contact is presented in a lead card:
  High   — verified corporate email, company website, or MCA KMP filing
  Medium — LinkedIn-sourced, activity within the last year
  Low    — LinkedIn-sourced and stale (>1 year), or unknown source
           (flag for manual verification on first call)
"""
from __future__ import annotations

from datetime import date


def _attr(contact, key):
    return contact[key] if isinstance(contact, dict) else getattr(contact, key)


def get_contact_confidence(contact) -> str:
    """Return 'High' | 'Medium' | 'Low' for a contact record."""
    if _attr(contact, "verified_via_signup"):
        return "High"  # corporate email verified via the self-disclosure loop

    source = _attr(contact, "source")
    if source in ("Company website", "MCA KMP filing"):
        return "High"

    if source == "LinkedIn":
        last = _attr(contact, "linkedin_last_updated")
        if not last:
            return "Low"
        days_stale = (date.today() - last).days
        if days_stale < 90:
            return "High"
        if days_stale < 360:
            return "Medium"
        return "Low"  # stale — flag for manual verification on first call

    return "Low"


if __name__ == "__main__":
    today = date.today()
    from datetime import timedelta

    verified = {"verified_via_signup": True, "source": "LinkedIn",
                "linkedin_last_updated": today - timedelta(days=1000)}
    website = {"verified_via_signup": False, "source": "Company website",
               "linkedin_last_updated": None}
    fresh_li = {"verified_via_signup": False, "source": "LinkedIn",
                "linkedin_last_updated": today - timedelta(days=30)}
    mid_li = {"verified_via_signup": False, "source": "LinkedIn",
              "linkedin_last_updated": today - timedelta(days=200)}
    stale_li = {"verified_via_signup": False, "source": "LinkedIn",
                "linkedin_last_updated": today - timedelta(days=500)}

    assert get_contact_confidence(verified) == "High"   # signup beats staleness
    assert get_contact_confidence(website) == "High"
    assert get_contact_confidence(fresh_li) == "High"
    assert get_contact_confidence(mid_li) == "Medium"
    assert get_contact_confidence(stale_li) == "Low"
    print("OK: confidence tiers — verified/website High, LinkedIn by recency.")
