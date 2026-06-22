"""Outcome endpoints — vendor submits a full outcome with reason."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_vendor
from api.models import OutcomeIn, OutcomeOut
from db.connection import fetch_one

router = APIRouter()


@router.post("", response_model=OutcomeOut)
def submit_outcome(body: OutcomeIn, vendor: dict = Depends(get_current_vendor)):
    """Record an outcome against one of the vendor's deliveries."""
    # Confirm the delivery belongs to this vendor before recording.
    delivery = fetch_one(
        "SELECT id FROM lead_delivery WHERE id = %s AND vendor_id = %s",
        (body.delivery_id, vendor["id"]))
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    from feedback.outcome_processor import record_outcome
    outcome_id = record_outcome(body.delivery_id, body.outcome_status,
                                body.reason_detail, captured_via="app")
    row = fetch_one("SELECT * FROM outcomes WHERE id = %s", (outcome_id,))
    return OutcomeOut(id=str(row["id"]), delivery_id=str(row["delivery_id"]),
                      outcome_status=row["outcome_status"],
                      captured_at=row["captured_at"])
