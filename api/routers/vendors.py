"""Vendor endpoints — register (public), profile read/update (authed)."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends

from api.deps import get_current_vendor
from api.models import (VendorOut, VendorRegister, VendorRegisterOut,
                        VendorUpdate)
from db.connection import fetch_one, get_cursor

router = APIRouter()


@router.post("/register", response_model=VendorRegisterOut)
def register_vendor(body: VendorRegister):
    """Public signup — stores the 4 MVP params, returns a fresh API key."""
    api_key = "fiq_" + secrets.token_urlsafe(24)
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO vendors
              (vendor_name, application_id, price_tier, geography,
               onboarding_complete, api_key)
            VALUES (%s, %s, %s, %s, TRUE, %s)
            RETURNING id
            """,
            (body.vendor_name, body.application_id, body.price_tier,
             body.geography, api_key),
        )
        new_id = str(cur.fetchone()["id"])
    return VendorRegisterOut(
        id=new_id, vendor_name=body.vendor_name,
        application_id=body.application_id, price_tier=body.price_tier,
        geography=body.geography, onboarding_complete=True, api_key=api_key)


@router.get("/me", response_model=VendorOut)
def get_me(vendor: dict = Depends(get_current_vendor)):
    return _to_out(vendor)


@router.patch("/me", response_model=VendorOut)
def update_me(body: VendorUpdate, vendor: dict = Depends(get_current_vendor)):
    """Update onboarding parameters (only the provided fields)."""
    fields = body.model_dump(exclude_none=True)
    if fields:
        sets = ", ".join(f"{k} = %s" for k in fields)
        params = list(fields.values()) + [vendor["id"]]
        with get_cursor() as cur:
            cur.execute(f"UPDATE vendors SET {sets} WHERE id = %s", tuple(params))
    updated = fetch_one("SELECT * FROM vendors WHERE id = %s", (vendor["id"],))
    return _to_out(updated)


def _to_out(v: dict) -> VendorOut:
    return VendorOut(
        id=str(v["id"]), vendor_name=v["vendor_name"],
        application_id=str(v["application_id"]) if v.get("application_id") else None,
        price_tier=v.get("price_tier"), geography=v.get("geography"),
        min_deal_size_inr=v.get("min_deal_size_inr"),
        onboarding_complete=v.get("onboarding_complete", False))
