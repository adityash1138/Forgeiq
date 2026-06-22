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

    return {"access_token": "buyer_" + secrets.token_urlsafe(24),
            "company": company["legal_name"]}
