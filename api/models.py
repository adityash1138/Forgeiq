"""Pydantic request/response models for the ForgeIQ API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# --- vendors ---------------------------------------------------------------
class VendorRegister(BaseModel):
    """The 4 MVP onboarding params a vendor supplies at signup."""
    vendor_name: str
    application_id: str
    price_tier: str               # Premium | Standard | Value
    geography: list[str]


class VendorOut(BaseModel):
    id: str
    vendor_name: str
    application_id: Optional[str] = None
    price_tier: Optional[str] = None
    geography: Optional[list[str]] = None
    min_deal_size_inr: Optional[int] = None
    onboarding_complete: bool = False


class VendorRegisterOut(VendorOut):
    api_key: str


class VendorUpdate(BaseModel):
    price_tier: Optional[str] = None
    geography: Optional[list[str]] = None
    min_deal_size_inr: Optional[int] = None


# --- leads -----------------------------------------------------------------
class LeadSummary(BaseModel):
    score_id: str
    company_name: str
    application_name: Optional[str] = None
    current_score: float
    status: str
    confidence_tier_shown: Optional[str] = None
    delivered_at: Optional[datetime] = None


class ContactOut(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    confidence_tier: Optional[str] = None
    email_pattern_guess: Optional[str] = None


class LeadDetail(LeadSummary):
    why_explanation: Optional[str] = None
    contacts: list[ContactOut] = []
    exclusivity_window_end: Optional[datetime] = None


# --- outcomes --------------------------------------------------------------
class OutcomeIn(BaseModel):
    delivery_id: str
    outcome_status: str           # Contacted | No response | Lost-Competitor | Won | Not-Relevant
    reason_detail: Optional[str] = None


class OutcomeOut(BaseModel):
    id: str
    delivery_id: str
    outcome_status: str
    captured_at: datetime
