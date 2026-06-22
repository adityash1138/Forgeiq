"""Shared API dependencies — vendor authentication.

Simple API-key auth for the MVP (upgrade to JWT later if needed). The key is
passed in the `x-api-key` header and matched against vendors.api_key.
"""
from __future__ import annotations

import os

from fastapi import Header, HTTPException

from db.connection import fetch_one


async def get_current_vendor(x_api_key: str = Header(...)) -> dict:
    """Resolve the authenticated vendor from the x-api-key header."""
    vendor = fetch_one("SELECT * FROM vendors WHERE api_key = %s", (x_api_key,))
    if not vendor:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return vendor


async def require_admin(x_admin_key: str = Header(...)) -> bool:
    """Gate admin endpoints behind the ADMIN_API_KEY env var.

    Set ADMIN_API_KEY in the environment (Railway/Render variables). If it is
    unset we fail closed — admin endpoints are unreachable until a key is set,
    so the founder console can never be left wide open by accident.
    """
    expected = os.environ.get("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(status_code=503,
                            detail="Admin console disabled: ADMIN_API_KEY not set")
    if x_admin_key != expected:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return True
