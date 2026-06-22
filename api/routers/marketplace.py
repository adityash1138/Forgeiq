"""Marketplace RFQ flow — the 6-step demand→match→proposal→close engine.

  1. Buyer posts a plain-language requirement brief        POST /rfqs
  2. ForgeIQ matches 3-5 vendors by capability + past deals (auto on create)
  3. Matched vendors see it briefed                         GET  /my-rfqs (vendor)
  4. Vendors submit custom proposals                        POST /rfqs/{id}/proposals
  5. Buyer shortlists; deal closes offline                  POST /rfqs/{id}/shortlist
  6. ForgeIQ records a lead-connection fee                  (set on shortlist)

Matching is deterministic (capability fit + past-deal track record), not a
black box: application match is required, geography overlap and delivered-lead
history rank the shortlist. This keeps it explainable and free of an API key.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_vendor, require_admin
from db.connection import fetch_all, fetch_one, get_cursor

router = APIRouter()

LEAD_FEE_INR = 35000           # ₹25-50K connection fee; mid-point default
MAX_MATCHES = 5


# ── models ──────────────────────────────────────────────────────────────────
class RFQCreate(BaseModel):
    title: str
    brief: str
    application_id: Optional[str] = None
    buyer_email: Optional[str] = None
    buyer_company: Optional[str] = None
    budget_range: Optional[str] = None
    geography: Optional[str] = None


class ProposalCreate(BaseModel):
    summary: str
    lead_time_weeks: Optional[int] = None
    price_indication: Optional[str] = None


# ── matching engine ─────────────────────────────────────────────────────────
def _match_vendors(rfq: dict) -> list[dict]:
    """Rank vendors for an RFQ. Capability (application) is required; geography
    overlap and past delivered-lead volume break ties."""
    vendors = fetch_all(
        """
        SELECT v.id, v.vendor_name, v.price_tier, v.geography, v.application_id,
               (SELECT COUNT(*) FROM lead_delivery ld WHERE ld.vendor_id = v.id)
                 AS deals
        FROM vendors v
        WHERE v.onboarding_complete = TRUE
          AND (%s IS NULL OR v.application_id = %s)
        """,
        (rfq.get("application_id"), rfq.get("application_id")))

    geo = (rfq.get("geography") or "").lower()
    ranked = []
    for v in vendors:
        score, reasons = 50, []
        if rfq.get("application_id") and str(v["application_id"]) == str(rfq["application_id"]):
            score += 30; reasons.append("application match")
        if geo and v["geography"]:
            if any(g.lower() in geo or geo in g.lower() for g in v["geography"]):
                score += 10; reasons.append("geography overlap")
        if v["deals"]:
            score += min(v["deals"] * 2, 10); reasons.append(f"{v['deals']} past deals")
        ranked.append({**v, "match_score": min(score, 100),
                       "match_reason": ", ".join(reasons) or "capability fit"})
    ranked.sort(key=lambda x: (x["match_score"], x["deals"]), reverse=True)
    return ranked[:MAX_MATCHES]


def _run_match(rfq_id: str) -> int:
    rfq = fetch_one("SELECT * FROM rfqs WHERE id = %s", (rfq_id,))
    if not rfq:
        return 0
    matches = _match_vendors(rfq)
    with get_cursor() as cur:
        for m in matches:
            cur.execute(
                """
                INSERT INTO rfq_matches (rfq_id, vendor_id, match_score, match_reason)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (rfq_id, vendor_id) DO UPDATE
                  SET match_score = EXCLUDED.match_score,
                      match_reason = EXCLUDED.match_reason
                """,
                (rfq_id, m["id"], m["match_score"], m["match_reason"]))
        cur.execute("UPDATE rfqs SET status = 'matched' WHERE id = %s "
                    "AND status = 'open'", (rfq_id,))
    return len(matches)


# ── 1+2. buyer posts brief → auto-match ─────────────────────────────────────
@router.post("/rfqs")
def create_rfq(body: RFQCreate):
    company_id = None
    if body.buyer_company:
        c = fetch_one("SELECT id FROM companies WHERE legal_name ILIKE %s",
                      (body.buyer_company,))
        company_id = c["id"] if c else None
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO rfqs (buyer_email, buyer_company, company_id, application_id,
                              title, brief, budget_range, geography)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (body.buyer_email, body.buyer_company, company_id, body.application_id,
             body.title, body.brief, body.budget_range, body.geography))
        rfq_id = str(cur.fetchone()["id"])
    matched = _run_match(rfq_id)
    return {"id": rfq_id, "status": "matched", "vendors_matched": matched}


# ── buyer/admin: list + detail ──────────────────────────────────────────────
@router.get("/rfqs")
def list_rfqs():
    return fetch_all(
        """
        SELECT r.id, r.title, r.buyer_company, r.status, r.created_at,
               a.application_name,
               (SELECT COUNT(*) FROM rfq_matches m WHERE m.rfq_id = r.id) AS matches,
               (SELECT COUNT(*) FROM proposals p WHERE p.rfq_id = r.id) AS proposals
        FROM rfqs r LEFT JOIN applications a ON a.id = r.application_id
        ORDER BY r.created_at DESC LIMIT 100
        """)


@router.get("/rfqs/{rfq_id}")
def rfq_detail(rfq_id: str):
    rfq = fetch_one(
        "SELECT r.*, a.application_name FROM rfqs r "
        "LEFT JOIN applications a ON a.id = r.application_id WHERE r.id = %s",
        (rfq_id,))
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    matches = fetch_all(
        "SELECT m.match_score, m.match_reason, v.vendor_name "
        "FROM rfq_matches m JOIN vendors v ON v.id = m.vendor_id "
        "WHERE m.rfq_id = %s ORDER BY m.match_score DESC", (rfq_id,))
    proposals = fetch_all(
        "SELECT p.id, p.summary, p.lead_time_weeks, p.price_indication, p.status, "
        "p.submitted_at, v.vendor_name FROM proposals p "
        "JOIN vendors v ON v.id = p.vendor_id WHERE p.rfq_id = %s "
        "ORDER BY p.submitted_at", (rfq_id,))
    return {"rfq": rfq, "matches": matches, "proposals": proposals}


# ── 3. vendor: RFQs matched to me ───────────────────────────────────────────
@router.get("/my-rfqs")
def my_rfqs(vendor: dict = Depends(get_current_vendor)):
    return fetch_all(
        """
        SELECT r.id, r.title, r.brief, r.budget_range, r.geography, r.status,
               r.created_at, a.application_name, m.match_score, m.match_reason,
               (SELECT p.status FROM proposals p
                WHERE p.rfq_id = r.id AND p.vendor_id = %s) AS my_proposal_status
        FROM rfq_matches m
        JOIN rfqs r ON r.id = m.rfq_id
        LEFT JOIN applications a ON a.id = r.application_id
        WHERE m.vendor_id = %s
        ORDER BY r.created_at DESC
        """,
        (vendor["id"], vendor["id"]))


# ── 4. vendor: submit proposal ──────────────────────────────────────────────
@router.post("/rfqs/{rfq_id}/proposals")
def submit_proposal(rfq_id: str, body: ProposalCreate,
                    vendor: dict = Depends(get_current_vendor)):
    match = fetch_one(
        "SELECT 1 FROM rfq_matches WHERE rfq_id = %s AND vendor_id = %s",
        (rfq_id, vendor["id"]))
    if not match:
        raise HTTPException(status_code=403, detail="Not matched to this RFQ")
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO proposals (rfq_id, vendor_id, summary, lead_time_weeks,
                                   price_indication)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (rfq_id, vendor_id) DO UPDATE
              SET summary = EXCLUDED.summary,
                  lead_time_weeks = EXCLUDED.lead_time_weeks,
                  price_indication = EXCLUDED.price_indication,
                  submitted_at = NOW()
            RETURNING id
            """,
            (rfq_id, vendor["id"], body.summary, body.lead_time_weeks,
             body.price_indication))
        pid = str(cur.fetchone()["id"])
        cur.execute("UPDATE rfqs SET status = 'proposals_in' WHERE id = %s "
                    "AND status IN ('open','matched')", (rfq_id,))
    return {"id": pid, "ok": True}


# ── 5+6. buyer shortlists → close + lead fee ────────────────────────────────
@router.post("/rfqs/{rfq_id}/shortlist")
def shortlist(rfq_id: str, proposal_id: str):
    prop = fetch_one("SELECT id FROM proposals WHERE id = %s AND rfq_id = %s",
                     (proposal_id, rfq_id))
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found for RFQ")
    with get_cursor() as cur:
        cur.execute("UPDATE proposals SET status = 'shortlisted' WHERE id = %s",
                    (proposal_id,))
        cur.execute("UPDATE proposals SET status = 'declined' "
                    "WHERE rfq_id = %s AND id <> %s", (rfq_id, proposal_id))
        cur.execute("UPDATE rfqs SET status = 'closed', lead_fee_inr = %s "
                    "WHERE id = %s", (LEAD_FEE_INR, rfq_id))
    return {"ok": True, "status": "closed", "lead_fee_inr": LEAD_FEE_INR}


# ── admin: re-run matching manually ─────────────────────────────────────────
@router.post("/rfqs/{rfq_id}/rematch", dependencies=[Depends(require_admin)])
def rematch(rfq_id: str):
    return {"vendors_matched": _run_match(rfq_id)}
