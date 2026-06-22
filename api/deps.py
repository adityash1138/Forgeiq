"""Shared API dependencies — vendor authentication.

Simple API-key auth for the MVP (upgrade to JWT later if needed). The key is
passed in the `x-api-key` header and matched against vendors.api_key.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

from db.connection import fetch_one


async def get_current_vendor(x_api_key: str = Header(...)) -> dict:
    """Resolve the authenticated vendor from the x-api-key header."""
    vendor = fetch_one("SELECT * FROM vendors WHERE api_key = %s", (x_api_key,))
    if not vendor:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return vendor
