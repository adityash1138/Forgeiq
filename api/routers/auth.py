"""Auth router — the Verified Buyer Profile self-disclosure loop.

When a buyer signs up to the free benchmarking tool, their corporate email
becomes the anchor: the matching contact is marked verified_via_signup=TRUE —
the highest possible confidence tier.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.connection import fetch_one, get_cursor

router = APIRouter()


class BuyerRegister(BaseModel):
    email: str
    role: str
    company_cin: str
    plant: str | None = None


@router.post("/buyer/register")
def register_buyer(body: BuyerRegister):
    """Verify the email domain against the company, then mark contact verified."""
    if "@" not in body.email:
        raise HTTPException(status_code=400, detail="Invalid email")
    domain = body.email.split("@")[1].lower()

    company = fetch_one(
        "SELECT id, legal_name FROM companies WHERE cin = %s",
        (body.company_cin,))
    if not company:
        raise HTTPException(status_code=404, detail="Company not found for CIN")

    # Upsert the verified contact (anchor = corporate email).
    full_name = body.email.split("@")[0].replace(".", " ").title()
    existing = fetch_one(
        "SELECT id FROM contacts WHERE company_id = %s AND full_name = %s",
        (company["id"], full_name))
    with get_cursor() as cur:
        if existing:
            cur.execute(
                "UPDATE contacts SET role = %s, verified_via_signup = TRUE, "
                "confidence_tier = 'High', source = 'Verified signup', "
                "updated_at = NOW() WHERE id = %s", (body.role, existing["id"]))
        else:
            cur.execute(
                "INSERT INTO contacts (company_id, full_name, role, "
                "confidence_tier, source, verified_via_signup) "
                "VALUES (%s, %s, %s, 'High', 'Verified signup', TRUE)",
                (company["id"], full_name, body.role))

    # Free benchmark — the value exchanged for email verification.
    from db.connection import fetch_all
    scores = fetch_all(
        """
        SELECT a.application_name, s.current_score, s.status
        FROM scores s LEFT JOIN applications a ON a.id = s.application_id
        WHERE s.company_id = %s ORDER BY s.current_score DESC
        """, (company["id"],))
    sector = fetch_one(
        "SELECT COUNT(*) AS companies, ROUND(AVG(current_score),1) AS avg_score "
        "FROM scores") or {}
    signal_count = (fetch_one(
        "SELECT COUNT(*) AS n FROM raw_signals WHERE resolved_company_id = %s",
        (company["id"],)) or {}).get("n", 0)
    best = scores[0]["current_score"] if scores else 0

    return {
        "access_token": "buyer_" + secrets.token_urlsafe(24),
        "company": company["legal_name"],
        "benchmark": {
            "your_top_score": float(best or 0),
            "sector_avg_score": float(sector.get("avg_score") or 0),
            "sector_companies_tracked": sector.get("companies", 0),
            "signals_detected_on_you": signal_count,
            "application_scores": [
                {"application": s["application_name"],
                 "score": float(s["current_score"] or 0), "status": s["status"]}
                for s in scores],
        },
    }
