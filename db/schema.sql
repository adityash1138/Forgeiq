-- ForgeIQ Database Schema — All 16 Tables
-- PostgreSQL (Supabase hosted)
--
-- IMPORTANT: Run this entire file in one block. Tables with foreign keys
-- must be created AFTER the tables they reference. The order below is correct.
-- Pasting partial sections will break foreign-key constraint ordering.

-- Enable UUID generation (Supabase has pgcrypto by default; this is a safety net)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- CORE REFERENCE TABLES (build first — everything depends on them)
-- ============================================================================

CREATE TABLE industries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  industry_name TEXT NOT NULL,
  status TEXT DEFAULT 'active',   -- active | planned
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE vendor_categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  industry_id UUID REFERENCES industries(id),
  category_name TEXT NOT NULL,
  category_type TEXT  -- Equipment | Component
);

CREATE TABLE applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  category_id UUID REFERENCES vendor_categories(id),
  application_name TEXT NOT NULL,
  production_line_type TEXT,  -- Battery Line | Body/Chassis Line | Powertrain Line
  buyer_profile TEXT,
  typical_price_tier TEXT     -- Premium-dominant | Value-dominant | Both
);

-- ============================================================================
-- SIGNAL CONFIG TABLES (store in DB not code — edit without deployment)
-- ============================================================================

CREATE TABLE signal_type_config (
  signal_type TEXT PRIMARY KEY,
  industry_id UUID REFERENCES industries(id),
  tier TEXT NOT NULL,          -- Tier1 | Tier2 | Tier3
  tier_weight NUMERIC(4,2),    -- 1.0 | 0.6 | 0.25
  base_strength INTEGER,       -- 1-10
  decay_curve TEXT,            -- Cliff | Wave | Burn
  peak_start_days INTEGER,
  peak_end_days INTEGER,
  total_decay_days INTEGER,
  is_cascade_trigger TEXT      -- Yes | No | Partial
);

CREATE TABLE cascade_wave_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trigger_signal_type TEXT REFERENCES signal_type_config(signal_type),
  application_id UUID REFERENCES applications(id),
  wave_order INTEGER,
  activate_month_start INTEGER,
  activate_month_end INTEGER,
  confirming_signal_types TEXT[]  -- array of signal_type strings
);

CREATE TABLE negative_signals_config (
  negative_signal_type TEXT PRIMARY KEY,
  severity_class TEXT,  -- Class1_Existential | Class2_Heavy | Class3_CategorySpecific
  multiplier NUMERIC(3,2),
  scope TEXT,           -- All_Applications | Single_Application
  auto_recovers BOOLEAN,
  recovery_trigger TEXT
);

-- ============================================================================
-- COMPANY IDENTITY TABLES
-- ============================================================================

CREATE TABLE companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  industry_id UUID REFERENCES industries(id),
  legal_name TEXT NOT NULL,
  known_aliases TEXT[],
  cin TEXT UNIQUE,
  plant_location TEXT,
  parent_company_id UUID REFERENCES companies(id),
  negative_flag TEXT DEFAULT 'None',
  negative_flag_date DATE,
  negative_flag_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE entity_resolution_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID,  -- references raw_signals
  raw_company_name TEXT,
  best_guess_company_id UUID REFERENCES companies(id),
  confidence_pct INTEGER,
  days_in_queue INTEGER DEFAULT 0,
  status TEXT DEFAULT 'Active',
  last_reattempt_at TIMESTAMPTZ,
  resolution_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- CORE DATA TABLES
-- ============================================================================

CREATE TABLE raw_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id TEXT UNIQUE,           -- SIG-XXXXX human-readable
  industry_id UUID REFERENCES industries(id),
  date_detected DATE NOT NULL,
  signal_type TEXT REFERENCES signal_type_config(signal_type),
  raw_company_name TEXT,
  resolved_company_id UUID REFERENCES companies(id),
  entity_confidence_pct INTEGER,
  resolution_tier TEXT,            -- A | B | C | D
  source TEXT,
  source_url TEXT,
  raw_text_snippet TEXT,
  application_tags UUID[],         -- array of application IDs
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID REFERENCES companies(id),
  application_id UUID REFERENCES applications(id),
  current_score NUMERIC(6,2),
  status TEXT,                     -- HOT | WARM | COLD
  negative_multiplier NUMERIC(3,2) DEFAULT 1.0,
  contributing_signal_ids UUID[],
  last_calculated_at TIMESTAMPTZ,
  UNIQUE(company_id, application_id)
);

CREATE TABLE cascade_state (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trigger_signal_id UUID REFERENCES raw_signals(id),
  company_id UUID REFERENCES companies(id),
  cascade_wave_id UUID REFERENCES cascade_wave_config(id),
  wave_status TEXT DEFAULT 'pending',  -- pending | confirmed | fired | paused
  earliest_fire_date DATE,
  latest_fire_date DATE,
  confirming_signal_id UUID,
  fired_at TIMESTAMPTZ
);

-- ============================================================================
-- CONTACT, COMPETITOR, AND DELIVERY TABLES
-- ============================================================================

CREATE TABLE contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID REFERENCES companies(id),
  full_name TEXT,
  role TEXT,
  chain_link TEXT,  -- Initiator | Approver | Signoff
  confidence_tier TEXT,
  source TEXT,
  linkedin_last_updated DATE,
  email_pattern_guess TEXT,
  verified_via_signup BOOLEAN DEFAULT FALSE,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE competitor_intelligence (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID REFERENCES companies(id),
  application_id UUID REFERENCES applications(id),
  competitor_brand TEXT,
  evidence_type TEXT,
  evidence_date DATE,
  confidence TEXT,
  recommended_move TEXT
);

CREATE TABLE vendors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vendor_name TEXT NOT NULL,
  industry_id UUID REFERENCES industries(id),
  application_id UUID REFERENCES applications(id),
  price_tier TEXT,
  geography TEXT[],
  min_deal_size_inr BIGINT,
  exclusivity_level TEXT,
  onboarding_complete BOOLEAN DEFAULT FALSE,
  api_key TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE lead_delivery (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  score_id UUID REFERENCES scores(id),
  vendor_id UUID REFERENCES vendors(id),
  delivered_at TIMESTAMPTZ DEFAULT NOW(),
  exclusivity_window_end TIMESTAMPTZ,
  confidence_tier_shown TEXT,
  contact_ids UUID[],
  why_explanation TEXT,
  human_spotcheck_done BOOLEAN DEFAULT FALSE
);

CREATE TABLE outcomes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  delivery_id UUID REFERENCES lead_delivery(id),
  outcome_status TEXT,
  reason_detail TEXT,
  captured_via TEXT,
  captured_at TIMESTAMPTZ DEFAULT NOW(),
  notes_for_recalibration TEXT
);

-- ============================================================================
-- JOB RUN LOG (scheduler observability)
-- ============================================================================

CREATE TABLE job_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name TEXT NOT NULL,
  status TEXT,                     -- success | failed | heartbeat
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ DEFAULT NOW(),
  error TEXT
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

CREATE INDEX idx_raw_signals_company ON raw_signals(resolved_company_id);
CREATE INDEX idx_raw_signals_type_date ON raw_signals(signal_type, date_detected);
CREATE INDEX idx_scores_company_app ON scores(company_id, application_id);
CREATE INDEX idx_scores_status ON scores(status);
CREATE INDEX idx_lead_delivery_vendor ON lead_delivery(vendor_id);
CREATE INDEX idx_cascade_state_company ON cascade_state(company_id, wave_status);
