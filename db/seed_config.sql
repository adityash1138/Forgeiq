-- ForgeIQ Config Seed Data
-- Run AFTER schema.sql. Seeds the reference + config tables so the scoring
-- engine, cascade engine, and negative handler have rules to operate on.
--
-- These rows live in the database (not code) so they can be edited without a
-- redeploy. The founder hand-tunes them from the outcomes table over time.

-- ----------------------------------------------------------------------------
-- Base industry (EV Manufacturing is the launch vertical)
-- ----------------------------------------------------------------------------
INSERT INTO industries (id, industry_name, status)
VALUES ('00000000-0000-0000-0000-000000000001', 'EV Manufacturing', 'active')
ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------
-- signal_type_config — all 13 signal sources
--   tier_weight: Tier1 = 1.0, Tier2 = 0.6, Tier3 = 0.25
--   Peak windows expressed in DAYS (months from blueprint converted at 30d)
-- ----------------------------------------------------------------------------
INSERT INTO signal_type_config
  (signal_type, industry_id, tier, tier_weight, base_strength,
   decay_curve, peak_start_days, peak_end_days, total_decay_days, is_cascade_trigger)
VALUES
  -- Tier 1
  ('GEM_TENDER',       '00000000-0000-0000-0000-000000000001', 'Tier1', 1.00, 8, 'Cliff',   0,   30, 120, 'No'),
  ('CAPEX_FILING',     '00000000-0000-0000-0000-000000000001', 'Tier1', 1.00, 10,'Wave',  120,  270, 540, 'Yes'),
  ('PLI_APPROVAL',     '00000000-0000-0000-0000-000000000001', 'Tier1', 1.00, 9, 'Wave',    0,  180, 540, 'Yes'),
  ('ICEGATE_IMPORT',   '00000000-0000-0000-0000-000000000001', 'Tier1', 1.00, 8, 'Wave',    0,  120, 360, 'Yes'),
  -- Tier 2
  ('JOB_POSTING',      '00000000-0000-0000-0000-000000000001', 'Tier2', 0.60, 6, 'Cliff',   0,   60, 150, 'No'),
  ('LAND_ACQUISITION', '00000000-0000-0000-0000-000000000001', 'Tier2', 0.60, 7, 'Wave',   30,  180, 540, 'Yes'),
  ('EC_CLEARANCE',     '00000000-0000-0000-0000-000000000001', 'Tier2', 0.60, 7, 'Burn',   60,  240, 540, 'Yes'),
  ('OEM_CONTRACT_WIN', '00000000-0000-0000-0000-000000000001', 'Tier2', 0.60, 7, 'Cliff',   0,   45, 180, 'No'),
  ('VC_PE_FUNDING',    '00000000-0000-0000-0000-000000000001', 'Tier2', 0.60, 6, 'Cliff',   0,   60, 240, 'No'),
  ('MCA_ROC_FILING',   '00000000-0000-0000-0000-000000000001', 'Tier2', 0.60, 5, 'Burn',   30,  180, 480, 'No'),
  -- Tier 3
  ('GST_NEW_STATE',    '00000000-0000-0000-0000-000000000001', 'Tier3', 0.25, 4, 'Cliff',   0,   45, 150, 'No'),
  ('LINKEDIN_ACTIVITY','00000000-0000-0000-0000-000000000001', 'Tier3', 0.25, 3, 'Cliff',   0,   30, 90,  'No'),
  ('NEWS_MENTION',     '00000000-0000-0000-0000-000000000001', 'Tier3', 0.25, 3, 'Cliff',   0,   30, 90,  'No')
ON CONFLICT (signal_type) DO NOTHING;

-- ----------------------------------------------------------------------------
-- negative_signals_config — 3 severity classes
-- ----------------------------------------------------------------------------
INSERT INTO negative_signals_config
  (negative_signal_type, severity_class, multiplier, scope, auto_recovers, recovery_trigger)
VALUES
  ('INSOLVENCY_NCLT',      'Class1_Existential',     0.00, 'All_Applications',  FALSE, NULL),
  ('PLANT_SHUTDOWN',       'Class1_Existential',     0.00, 'All_Applications',  FALSE, NULL),
  ('MAJOR_LAYOFFS',        'Class2_Heavy',           0.10, 'All_Applications',  TRUE,  '90_days_elapsed'),
  ('CREDIT_DOWNGRADE',     'Class2_Heavy',           0.10, 'All_Applications',  TRUE,  '90_days_elapsed'),
  ('COMPETITOR_LOCKED_IN', 'Class3_CategorySpecific',0.30, 'Single_Application',TRUE,  'competitor_contract_expiry'),
  ('CATEGORY_INSOURCED',   'Class3_CategorySpecific',0.30, 'Single_Application',TRUE,  'insourcing_reversal_signal')
ON CONFLICT (negative_signal_type) DO NOTHING;

-- ----------------------------------------------------------------------------
-- cascade_wave_config is seeded per-application once the applications table is
-- populated for the industry. It is intentionally left to a data-entry step
-- (see config/cascade_wave_config.json) because application_id is a live UUID.
-- ----------------------------------------------------------------------------
