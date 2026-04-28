-- Migration 003: Per-job scraper schedule table
-- Replaces the single global SCRAPER_MIN_INTERVAL_MINUTES with per-job tracking.
--
-- Three jobs:
--   regular_ats  - Greenhouse/Lever/Comeet/BambooHR/Ashby/Workday, Israeli jobs only, every 2h
--   new_ats      - iCIMS/Jobvite, Israeli jobs only, twice a day (~12h)
--   usa_digest   - All ATS, USA jobs only + send digest, once a day (~23h)

CREATE TABLE IF NOT EXISTS scraper_schedule (
    job_name         TEXT PRIMARY KEY,
    description      TEXT,
    min_interval_min INT  NOT NULL DEFAULT 110,
    last_run_at      TIMESTAMPTZ,
    next_run_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_status      TEXT         NOT NULL DEFAULT 'idle',
    last_jobs_found  INT          NOT NULL DEFAULT 0,
    is_enabled       BOOLEAN      NOT NULL DEFAULT TRUE,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

INSERT INTO scraper_schedule (job_name, description, min_interval_min, next_run_at) VALUES
    ('regular_ats', 'Greenhouse/Lever/Comeet/BambooHR/Ashby/Workday — Israeli jobs only', 110,  NOW()),
    ('new_ats',     'iCIMS/Jobvite — Israeli jobs only',                                   660,  NOW()),
    ('usa_digest',  'All ATS — USA jobs only + send nightly digest',                       1380, NOW())
ON CONFLICT (job_name) DO NOTHING;
