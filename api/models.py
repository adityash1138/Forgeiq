"""Pydantic request/response models for the ForgeIQ API."""
from __future__ import annotations

from datetime import date, datetime
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


class SignalTimelineItem(BaseModel):
    signal_type: str
    label: str
    tier: Optional[str] = None
    date_detected: Optional[date] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    snippet: Optional[str] = None
    decay_position: Optional[float] = None       # 0-1 how "live" the signal is
    contribution: Optional[float] = None          # points it added to raw score


class CompetitorIntelOut(BaseModel):
    competitor_brand: Optional[str] = None
    evidence_type: Optional[str] = None
    evidence_date: Optional[date] = None
    confidence: Optional[str] = None
    recommended_move: Optional[str] = None


class ScoreBreakdown(BaseModel):
    final_score: float
    pre_adjustment_score: float                   # before negative multiplier
    negative_multiplier: float
    negative_flag: Optional[str] = None
    max_possible: float


class LeadDetail(LeadSummary):
    why_explanation: Optional[str] = None
    contacts: list[ContactOut] = []
    exclusivity_window_end: Optional[datetime] = None
    plant_location: Optional[str] = None
    signal_timeline: list[SignalTimelineItem] = []
    competitor_intel: list[CompetitorIntelOut] = []
    score_breakdown: Optional[ScoreBreakdown] = None


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
