"""Lead endpoints — list + detail + mark-contacted, all vendor-scoped."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_current_vendor
from api.models import ContactOut, LeadDetail, LeadSummary
from db.connection import fetch_all, fetch_one, get_cursor

router = APIRouter()


@router.get("", response_model=list[LeadSummary])
def list_leads(
    status: str | None = Query(None),
    application_id: str | None = Query(None),
    city: str | None = Query(None),
    vendor: dict = Depends(get_current_vendor),
):
    """List leads delivered to the authenticated vendor, filterable."""
    clauses = ["ld.vendor_id = %s"]
    params: list = [vendor["id"]]
    if status:
        clauses.append("s.status = %s")
        params.append(status)
    if application_id:
        clauses.append("s.application_id = %s")
        params.append(application_id)
    if city:
        clauses.append("c.plant_location ILIKE %s")
        params.append(f"%{city}%")

    rows = fetch_all(
        f"""
        SELECT s.id AS score_id, c.legal_name AS company_name,
               a.application_name, s.current_score, s.status,
               ld.confidence_tier_shown, ld.delivered_at
        FROM lead_delivery ld
        JOIN scores s ON s.id = ld.score_id
        JOIN companies c ON c.id = s.company_id
        LEFT JOIN applications a ON a.id = s.application_id
        WHERE {' AND '.join(clauses)}
        ORDER BY ld.delivered_at DESC
        """,
        tuple(params),
    )
    return [_summary(r) for r in rows]


@router.get("/{score_id}", response_model=LeadDetail)
def lead_detail(score_id: str, vendor: dict = Depends(get_current_vendor)):
    """Full lead detail — signals (why), contacts, competitor intel."""
    row = fetch_one(
        """
        SELECT s.id AS score_id, c.legal_name AS company_name,
               a.application_name, s.current_score, s.status,
               ld.confidence_tier_shown, ld.delivered_at, ld.why_explanation,
               ld.exclusivity_window_end, ld.contact_ids
        FROM lead_delivery ld
        JOIN scores s ON s.id = ld.score_id
        JOIN companies c ON c.id = s.company_id
        LEFT JOIN applications a ON a.id = s.application_id
        WHERE s.id = %s AND ld.vendor_id = %s
        ORDER BY ld.delivered_at DESC LIMIT 1
        """,
        (score_id, vendor["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    contacts = []
    if row["contact_ids"]:
        contacts = fetch_all(
            "SELECT full_name, role, confidence_tier, email_pattern_guess "
            "FROM contacts WHERE id = ANY(%s::uuid[])", (row["contact_ids"],))

    detail = _summary(row)
    detail.update({
        "why_explanation": row["why_explanation"],
        "exclusivity_window_end": row["exclusivity_window_end"],
        "contacts": [ContactOut(**c) for c in contacts],
    })
    return detail


@router.post("/{score_id}/mark-contacted")
def mark_contacted(score_id: str, vendor: dict = Depends(get_current_vendor)):
    """Record a 'Contacted' outcome for the vendor's delivery of this score."""
    delivery = fetch_one(
        "SELECT id FROM lead_delivery WHERE score_id = %s AND vendor_id = %s "
        "ORDER BY delivered_at DESC LIMIT 1", (score_id, vendor["id"]))
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO outcomes (delivery_id, outcome_status, captured_via) "
            "VALUES (%s, 'Contacted', 'app')", (delivery["id"],))
    return {"ok": True, "delivery_id": str(delivery["id"])}


def _summary(row: dict) -> dict:
    return {
        "score_id": str(row["score_id"]),
        "company_name": row["company_name"],
        "application_name": row.get("application_name"),
        "current_score": float(row["current_score"] or 0),
        "status": row["status"],
        "confidence_tier_shown": row.get("confidence_tier_shown"),
        "delivered_at": row.get("delivered_at"),
    }
