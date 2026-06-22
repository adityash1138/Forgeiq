"""Contact sourcing — runs after a score crosses WARM (40+), before delivery.

Only companies actually being prepared for delivery are sourced, to keep API
and scraping costs down. Sourcing hierarchy (best confidence first):

  1. Company-disclosed: website 'Contact Us' / 'Leadership', GeM buyer profile
  2. MCA KMP (Key Managerial Personnel) filings — Plant Head / VP Operations
  3. LinkedIn profile match — name, title, profile URL, last-activity date
  4. Email-pattern inference — apply a confirmed corporate pattern to names

Each sourced contact is upserted into the contacts table and assigned a
confidence tier by staleness_detector.
"""
from __future__ import annotations

from db.connection import fetch_all, fetch_one, get_cursor
from contact.staleness_detector import get_contact_confidence

WARM_THRESHOLD = 40.0


# --- individual source adapters (network/parse stubs to fill in per source) ---
def scrape_company_website_contacts(company: dict) -> list[dict]:
    """Parse the company's 'Contact Us' / 'Leadership' page. Highest confidence.

    Returns a list of contact dicts. Left as a thin adapter — wire the real
    fetch+parse per company website. Source tag drives confidence = High.
    """
    return []


def fetch_mca_kmp(cin: str | None) -> list[dict]:
    """MCA mandates KMP disclosure for listed companies — Plant Head / VP Ops."""
    if not cin:
        return []
    return []


def linkedin_search_contacts(legal_name: str, location: str | None) -> list[dict]:
    """Search LinkedIn for '<company> Procurement Manager <city>'.

    Returns name, role, profile URL, and last-activity date for staleness.
    """
    return []


def infer_email_pattern(contacts: list[dict]) -> None:
    """If any contact has a confirmed corporate email, apply its pattern to
    LinkedIn-sourced names that lack one. Mutates contacts in place."""
    confirmed = next((c for c in contacts if c.get("email_pattern_guess")
                      and c.get("source") == "Company website"), None)
    if not confirmed:
        return
    pattern = confirmed["email_pattern_guess"]
    for c in contacts:
        if not c.get("email_pattern_guess"):
            c["email_pattern_guess"] = pattern


# --------------------------------------------------------------------- main
def source_contacts(company_id: str,
                    score_threshold: float = WARM_THRESHOLD) -> int:
    """Source + persist contacts for a company if any score is WARM+.

    Returns the number of contacts upserted.
    """
    top = fetch_one(
        "SELECT MAX(current_score) AS s FROM scores WHERE company_id = %s",
        (company_id,))
    if not top or top["s"] is None or float(top["s"]) < score_threshold:
        return 0

    company = fetch_one(
        "SELECT legal_name, plant_location, cin FROM companies WHERE id = %s",
        (company_id,))
    if not company:
        return 0

    contacts: list[dict] = []
    contacts += scrape_company_website_contacts(company)
    contacts += fetch_mca_kmp(company["cin"])
    contacts += linkedin_search_contacts(company["legal_name"],
                                         company["plant_location"])
    infer_email_pattern(contacts)

    for contact in contacts:
        _upsert_contact(company_id, contact)
    return len(contacts)


def _upsert_contact(company_id: str, contact: dict) -> None:
    """Update an existing contact (same company + name) or insert a new one."""
    confidence = get_contact_confidence(contact)
    existing = fetch_one(
        "SELECT id FROM contacts WHERE company_id = %s AND full_name = %s",
        (company_id, contact.get("full_name")))
    with get_cursor() as cur:
        if existing:
            cur.execute(
                """
                UPDATE contacts SET role = %s, chain_link = %s,
                  confidence_tier = %s, source = %s, linkedin_last_updated = %s,
                  email_pattern_guess = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (contact.get("role"), contact.get("chain_link"), confidence,
                 contact.get("source"), contact.get("linkedin_last_updated"),
                 contact.get("email_pattern_guess"), existing["id"]),
            )
        else:
            cur.execute(
                """
                INSERT INTO contacts
                  (company_id, full_name, role, chain_link, confidence_tier,
                   source, linkedin_last_updated, email_pattern_guess)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (company_id, contact.get("full_name"), contact.get("role"),
                 contact.get("chain_link"), confidence, contact.get("source"),
                 contact.get("linkedin_last_updated"),
                 contact.get("email_pattern_guess")),
            )


def source_for_new_warm_leads() -> int:
    """Pipeline entry: source contacts for every company with a WARM+ score."""
    companies = fetch_all(
        "SELECT DISTINCT company_id FROM scores WHERE current_score >= %s",
        (WARM_THRESHOLD,))
    total = 0
    for c in companies:
        total += source_contacts(str(c["company_id"]))
    print(f"contact_sourcer: sourced contacts for {len(companies)} warm "
          f"companies ({total} contacts).")
    return total


if __name__ == "__main__":
    # Offline: verify email-pattern inference propagation.
    contacts = [
        {"full_name": "A Rao", "source": "Company website",
         "email_pattern_guess": "first.last@acme.com"},
        {"full_name": "B Singh", "source": "LinkedIn",
         "email_pattern_guess": None},
    ]
    infer_email_pattern(contacts)
    print(contacts)
    assert contacts[1]["email_pattern_guess"] == "first.last@acme.com"
    print("OK: confirmed corporate email pattern propagates to LinkedIn names.")
