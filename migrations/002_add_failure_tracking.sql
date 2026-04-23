-- Migration: Add failure tracking columns to company_data table
-- Date: 2026-01-24
-- Description: Adds columns for tracking company scrape failures

-- Add failure tracking columns to company_data table
ALTER TABLE company_data
ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_success TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS last_failure TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS last_error TEXT,
ADD COLUMN IF NOT EXISTS total_jobs_scraped INTEGER DEFAULT 0;

-- Create index for querying failed companies
CREATE INDEX IF NOT EXISTS idx_company_data_failures 
ON company_data(consecutive_failures) 
WHERE consecutive_failures > 0;

-- Create index for active companies with failures
CREATE INDEX IF NOT EXISTS idx_company_data_active_failures 
ON company_data(is_active, consecutive_failures) 
WHERE is_active = true AND consecutive_failures > 0;

-- Add comment explaining the columns
COMMENT ON COLUMN company_data.consecutive_failures IS 'Number of consecutive scrape failures. Resets to 0 on success.';
COMMENT ON COLUMN company_data.last_success IS 'Timestamp of last successful scrape';
COMMENT ON COLUMN company_data.last_failure IS 'Timestamp of last failed scrape attempt';
COMMENT ON COLUMN company_data.last_error IS 'Error message from last failure (truncated to 500 chars)';
COMMENT ON COLUMN company_data.total_jobs_scraped IS 'Total number of jobs scraped from this company (cumulative)';

-- Create a view for easily identifying problematic companies
CREATE OR REPLACE VIEW companies_with_issues AS
SELECT 
    company,
    link_type,
    consecutive_failures,
    last_success,
    last_failure,
    last_error,
    is_active,
    CASE 
        WHEN consecutive_failures >= 10 THEN 'CRITICAL'
        WHEN consecutive_failures >= 5 THEN 'WARNING'
        WHEN consecutive_failures >= 3 THEN 'WATCH'
        ELSE 'OK'
    END AS health_status
FROM company_data
WHERE consecutive_failures > 0
ORDER BY consecutive_failures DESC;

-- Create function to reset all failures (for maintenance)
CREATE OR REPLACE FUNCTION reset_all_company_failures()
RETURNS INTEGER AS $$
DECLARE
    affected_rows INTEGER;
BEGIN
    UPDATE company_data
    SET 
        consecutive_failures = 0,
        last_error = NULL,
        is_active = true,
        updated_at = NOW()
    WHERE consecutive_failures > 0;
    
    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows;
END;
$$ LANGUAGE plpgsql;
