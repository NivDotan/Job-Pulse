-- Migration: Create company_data and scraper_log_runs tables
-- Run this in your Supabase SQL editor

-- ============================================
-- Table: company_data
-- Stores company information (replaces JSON file reads)
-- ============================================

CREATE TABLE IF NOT EXISTS public.company_data (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company text NOT NULL,
    link_type text NOT NULL,
    unique_identifier text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT company_data_company_linktype_unique UNIQUE (company, link_type)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_company_data_company ON public.company_data(company);
CREATE INDEX IF NOT EXISTS idx_company_data_link_type ON public.company_data(link_type);
CREATE INDEX IF NOT EXISTS idx_company_data_active ON public.company_data(is_active);

-- ============================================
-- Table: scraper_log_runs
-- Stores metadata for each scraper run (replaces filesystem log reads)
-- ============================================

CREATE TABLE IF NOT EXISTS public.scraper_log_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    log_filename text NOT NULL UNIQUE,
    start_time timestamp with time zone,
    end_time timestamp with time zone,
    duration_seconds integer,
    companies_processed integer DEFAULT 0,
    total_companies integer DEFAULT 0,
    jobs_found integer DEFAULT 0,
    jobs_filtered integer DEFAULT 0,
    error_count integer DEFAULT 0,
    warning_count integer DEFAULT 0,
    status text DEFAULT 'running',
    ats_breakdown jsonb,
    top_locations jsonb,
    error_summary jsonb,
    created_at timestamp with time zone DEFAULT now()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_scraper_log_runs_start_time ON public.scraper_log_runs(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_scraper_log_runs_status ON public.scraper_log_runs(status);
CREATE INDEX IF NOT EXISTS idx_scraper_log_runs_filename ON public.scraper_log_runs(log_filename);

-- ============================================
-- Function: Update updated_at timestamp
-- ============================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for company_data updated_at
DROP TRIGGER IF EXISTS update_company_data_updated_at ON public.company_data;
CREATE TRIGGER update_company_data_updated_at
    BEFORE UPDATE ON public.company_data
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- Grant permissions (Supabase RLS)
-- ============================================

-- Enable RLS
ALTER TABLE public.company_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scraper_log_runs ENABLE ROW LEVEL SECURITY;

-- Create policies for authenticated access (adjust as needed)
CREATE POLICY "Allow all operations on company_data" ON public.company_data
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow all operations on scraper_log_runs" ON public.scraper_log_runs
    FOR ALL USING (true) WITH CHECK (true);

-- For service role access (used by your Python scripts)
-- The service role key bypasses RLS, so these policies mainly affect anon/authenticated access

COMMENT ON TABLE public.company_data IS 'Stores company information for job scraping - migrated from JSON files';
COMMENT ON TABLE public.scraper_log_runs IS 'Stores metadata for each scraper run - replaces filesystem log parsing';
