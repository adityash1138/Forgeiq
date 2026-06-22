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
               c.plant_location, a.application_name, s.current_score, s.status,
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

    company_id, application_id = _score_company_app(score_id)

    detail = _summary(row)
    detail.update({
        "why_explanation": row["why_explanation"],
        "exclusivity_window_end": row["exclusivity_window_end"],
        "plant_location": row.get("plant_location"),
        "contacts": [ContactOut(**c) for c in contacts],
        "signal_timeline": _signal_timeline(company_id, application_id),
        "competitor_intel": _competitor_intel(company_id, application_id),
        "score_breakdown": _score_breakdown(score_id),
    })
    return detail


def _score_company_app(score_id: str) -> tuple[str, str]:
    row = fetch_one(
        "SELECT company_id, application_id FROM scores WHERE id = %s", (score_id,))
    return (str(row["company_id"]), str(row["application_id"])) if row else ("", "")


def _signal_timeline(company_id: str, application_id: str) -> list[dict]:
    """Every signal contributing to this Company x Application, newest first,
    with its tier, decay position, and points contributed — the transparent
    'why' behind the score."""
    from datetime import date as _date
    from engine.decay_calculator import calculate_decay_position
    from delivery.card_generator import SIGNAL_HUMAN_LABELS

    rows = fetch_all(
        """
        SELECT rs.signal_type, rs.date_detected, rs.source, rs.source_url,
               rs.raw_text_snippet, c.tier, c.base_strength, c.tier_weight,
               c.decay_curve, c.peak_start_days, c.peak_end_days, c.total_decay_days
        FROM raw_signals rs
        JOIN signal_type_config c ON c.signal_type = rs.signal_type
        WHERE rs.resolved_company_id = %s AND %s = ANY(rs.application_tags)
        ORDER BY rs.date_detected DESC
        """,
        (company_id, application_id))

    out = []
    for r in rows:
        days = (_date.today() - r["date_detected"]).days if r["date_detected"] else 0
        decay = calculate_decay_position(r, days)
        contribution = (r["base_strength"] or 0) * float(r["tier_weight"] or 0) * decay
        out.append({
            "signal_type": r["signal_type"],
            "label": SIGNAL_HUMAN_LABELS.get(r["signal_type"], r["signal_type"]),
            "tier": r["tier"],
            "date_detected": r["date_detected"],
            "source": r["source"],
            "source_url": r["source_url"],
            "snippet": r["raw_text_snippet"],
            "decay_position": round(decay, 3),
            "contribution": round(contribution, 2),
        })
    return out


def _competitor_intel(company_id: str, application_id: str) -> list[dict]:
    return fetch_all(
        """
        SELECT competitor_brand, evidence_type, evidence_date, confidence,
               recommended_move
        FROM competitor_intelligence
        WHERE company_id = %s AND (application_id = %s OR application_id IS NULL)
        ORDER BY evidence_date DESC NULLS LAST
        """,
        (company_id, application_id))


def _score_breakdown(score_id: str) -> dict | None:
    from engine.scoring_engine import MAX_POSSIBLE
    row = fetch_one(
        """
        SELECT s.current_score, s.negative_multiplier, c.negative_flag
        FROM scores s JOIN companies c ON c.id = s.company_id
        WHERE s.id = %s
        """, (score_id,))
    if not row:
        return None
    final = float(row["current_score"] or 0)
    mult = float(row["negative_multiplier"] or 1.0)
    pre = round(final / mult, 2) if mult else final
    return {
        "final_score": final,
        "pre_adjustment_score": pre,
        "negative_multiplier": mult,
        "negative_flag": row["negative_flag"] if row["negative_flag"] != "None" else None,
        "max_possible": MAX_POSSIBLE,
    }


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


@router.post("/{score_id}/outcome")
def log_outcome(score_id: str, body: dict,
                vendor: dict = Depends(get_current_vendor)):
    """Record a full outcome (status + optional reason) against the vendor's
    latest delivery of this score — the in-app equivalent of the 14-day ping."""
    status = (body or {}).get("outcome_status")
    if not status:
        raise HTTPException(status_code=400, detail="outcome_status required")
    delivery = fetch_one(
        "SELECT id FROM lead_delivery WHERE score_id = %s AND vendor_id = %s "
        "ORDER BY delivered_at DESC LIMIT 1", (score_id, vendor["id"]))
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    from feedback.outcome_processor import record_outcome
    oid = record_outcome(str(delivery["id"]), status,
                         (body or {}).get("reason_detail"), captured_via="app")
    return {"ok": True, "outcome_id": str(oid)}


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
