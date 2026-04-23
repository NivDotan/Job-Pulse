# Job Scraper System Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Data Flow](#data-flow)
4. [Supported ATS Platforms](#supported-ats-platforms)
5. [Core Components](#core-components)
6. [Database Schema](#database-schema)
7. [Email System](#email-system)
8. [LLM Integration](#llm-integration)
9. [Monitoring & Alerting](#monitoring--alerting)
10. [Manual Commands & Scripts](#manual-commands--scripts)
11. [Configuration](#configuration)
12. [Troubleshooting](#troubleshooting)
13. [Analytics (desc_reqs_scrapers)](#analytics-desc_reqs_scrapers)
14. [Cron job & HTTP trigger](#cron-job--http-trigger)

---

## System Overview

The Job Scraper System is an automated job aggregation platform that:
- Scrapes job listings from **400+ Israeli tech companies** across multiple ATS platforms
- Filters jobs for **junior/student positions** using keyword matching and LLM classification
- Sends **daily email notifications** with new relevant positions
- Provides a **real-time dashboard** for monitoring scraper health
- Tracks **company failures** and auto-deactivates problematic sources

### Key Features
- Multi-threaded scraping for performance
- Intelligent job classification using local LLM (LM Studio)
- Deduplication to avoid sending duplicate jobs
- Scheduled execution with configurable hours
- Comprehensive error tracking and alerting

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ENTRY POINT                                     │
│                          CleanScript.py (main)                               │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SCRAPING LAYER                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Greenhouse  │  │    Lever     │  │   Comeet     │  │  BambooHR    │    │
│  │     API      │  │     API      │  │   Scraper    │  │     API      │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │    Ashby     │  │   Workday    │  │    iCIMS     │  │   Jobvite    │    │
│  │     API      │  │     API      │  │   Scraper    │  │     API      │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROCESSING LAYER                                     │
│                      telegramInsertBot.py                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  1. Filter Israel-based jobs                                          │  │
│  │  2. Deduplicate against today's sent jobs                            │  │
│  │  3. Process with LLM for junior suitability                          │  │
│  │  4. Send email notification                                           │  │
│  │  5. Save to Supabase history                                          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                                          │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐         │
│  │     Supabase     │  │   JSON Files     │  │   Log Files      │         │
│  │    (Primary)     │  │   (Fallback)     │  │   (./logs/)      │         │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘         │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MONITORING LAYER                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐         │
│  │   DashboardApp   │  │    Alerting      │  │   Log Cleanup    │         │
│  │   (Flask:5050)   │  │   (alerting.py)  │  │ (log_cleanup.py) │         │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
Open-Jobs-Web-Backend/
├── Scrapers/                    # Main scraping code
│   ├── CleanScript.py           # Main entry point
│   ├── telegramInsertBot.py     # Job processing & email
│   ├── db_operations.py         # Database operations
│   ├── alerting.py              # Email alerts system
│   ├── log_cleanup.py           # Log maintenance
│   ├── comeet_scraper.py        # Comeet-specific scraper
│   ├── local_llm_function.py    # LLM integration
│   ├── .env                     # Configuration
│   └── logs/                    # Scraper logs
├── DashboardApp/                # Monitoring dashboard
│   ├── app.py                   # Flask application
│   ├── templates/index.html     # Dashboard UI
│   └── static/                  # CSS/JS assets
├── airflow_processes/data/      # Company data files
│   └── combined_company_data3.json
├── migrations/                  # Database migrations
└── deduplicated_links_for_bot.json  # Scraper output
```

---

## Data Flow

### 1. Scraping Phase
```
Company Data (JSON/DB) → CleanScript.py → ATS APIs → Raw Job Listings
```

### 2. Processing Phase
```
Raw Jobs → Filter (Israel) → ETL Script → Deduplicate → LLM Classification
```

### 3. Database Sync Phase (scrapers_data table)
The `process_and_sync_data()` function compares scraped jobs with existing DB records:
```
┌─────────────────────────────────────────────────────────────────────────┐
│                     process_and_sync_data()                              │
├─────────────────────────────────────────────────────────────────────────┤
│  New Scrape Data ──┬── Compare ──┬── Records in both → Keep (no change) │
│                    │    (merge)  │                                       │
│  Existing DB Data ─┘             ├── Only in scrape → INSERT (new jobs) │
│                                  │                                       │
│                                  └── Only in DB → DELETE (closed jobs)  │
└─────────────────────────────────────────────────────────────────────────┘
```

**INSERT:** New jobs found in scrape that don't exist in DB → Added to `scrapers_data`
**DELETE:** Jobs in DB that no longer appear in career pages → Removed from `scrapers_data`

### 4. Notification Phase
```
Classified Jobs → Email Builder → SMTP (Gmail) → Recipients
                              ↓
                    Supabase (emailed_jobs_history)
```

### 5. Monitoring Phase
```
Log Files → parse_log_file_for_metadata() → scraper_log_runs table → Dashboard
```

---

## Supported ATS Platforms

### Primary ATS Types (Fully Supported)

| ATS Type | LinkType Value | API/Method | Notes |
|----------|---------------|------------|-------|
| **Greenhouse** | `green` | REST API | `boards-api.greenhouse.io/v1/boards/{company}/jobs` |
| **Lever** | `lever` | REST API | Auto-detects US/EU, auto-lowercases company name |
| **Comeet** | `comeet` | HTML Scraping | Extracts `COMPANY_POSITIONS_DATA` from page |
| **BambooHR** | `bamboohr` | REST API | `{company}.bamboohr.com/careers/list` |
| **SmartRecruiters** | `smart` | HTML Scraping | Selenium-based extraction |

### Lever API Details

The Lever scraper automatically handles common issues:
- **US vs EU API**: Tries US (`api.lever.co`) first, then EU (`api.eu.lever.co`) if US returns 404
- **Case sensitivity**: Tries original company name, then lowercase (e.g., `WalkMe` → `walkme`)
- **No manual configuration needed**: Just add company name to DB, the scraper figures out the rest

Companies that use EU API (auto-detected): Mobileye, and others

### Additional ATS Types (Recently Added)

| ATS Type | LinkType Value | API/Method | Notes |
|----------|---------------|------------|-------|
| **Ashby** | `ashby` | REST API | `api.ashbyhq.com/posting-api/job-board/{company}` |
| **Workday** | `workday` | REST API | POST to `{company}.wd5.myworkdayjobs.com/wday/cxs/` |
| **iCIMS** | `icims` | HTML Scraping | `careers-{company}.icims.com/jobs/search` |
| **Jobvite** | `jobvite` | REST/HTML | `jobs.jobvite.com/careers/{company}/jobs` |

### Company Data Format

```json
{
    "Company": "monday",
    "LinkType": "comeet",
    "Unique Identifier": "41.00B"
}
```

For Comeet companies, the `Unique Identifier` is required.
For Workday companies, optionally include `"Workday Instance": "URL"`.

---

## Core Components

### CleanScript.py (Main Entry Point)

**Purpose:** Orchestrates the entire scraping process.

**Key Functions:**
- `JobScraper.main()` - Main scraping loop with threading
- `JobScraper.process_job_data()` - Process individual company
- `JobScraper.scrapers()` - Route to appropriate ATS scraper
- `is_within_schedule()` - Check if within allowed hours

**Execution:**
```bash
cd Scrapers
python CleanScript.py
```

**What it does:**
1. Starts Flask dashboard on port 5050
2. Opens ngrok tunnel for remote access
3. Loads company data from DB (fallback: JSON)
4. Scrapes all companies using thread pool (6 workers)
5. Saves results to `deduplicated_links_for_bot.json`
6. Calls `telegram_main()` to process and email jobs
7. Saves log metadata to database
8. Runs log cleanup (once per day)
9. Sleeps for configured interval (default: 2 hours)
10. Repeats

### telegramInsertBot.py (Job Processing & Email)

**Purpose:** Processes scraped jobs and sends email notifications.

**Key Functions:**
- `main()` - Entry point for job processing
- `test()` - Process jobs with LLM classification
- `SendEmail()` - Build and send HTML email
- `is_location_in_israel()` - Filter for Israel-based jobs
- `get_data_from_comeet()` - Extract job description from Comeet
- `get_data_from_greenhouse()` - Extract job description from Greenhouse

**Data Flow:**
1. Read `deduplicated_links_for_bot_unclean.json`
2. Filter for Israel locations
3. Run Spark ETL to process data
4. Compare with existing DB records (find new jobs)
5. For each new job:
   - Try LLM classification
   - If LLM unavailable: use keyword matching fallback
6. Send email with categorized jobs
7. Save sent jobs to Supabase `emailed_jobs_history`

### db_operations.py (Database Layer)

**Purpose:** All Supabase database operations.

**Key Functions:**
- `get_all_companies()` - Fetch active companies
- `sync_companies_from_json()` - Sync JSON to DB
- `record_company_success()` - Track successful scrape
- `record_company_failure()` - Track failed scrape
- `get_companies_with_failures()` - Get problematic companies
- `parse_log_file_for_metadata()` - Extract metrics from log
- `save_log_metadata()` - Save metrics to DB

### alerting.py (Alert System)

**Purpose:** Send email alerts for system issues.

**Alert Types:**
- `HIGH_ERROR_RATE` - >20% of companies failing
- `COMPANY_FAILURES` - Companies with 5+ consecutive failures
- `NO_JOBS_FOUND` - No jobs found in 24+ hours
- `SCRAPER_CRASH` - Scraper crashed unexpectedly
- `CRITICAL_ERROR` - Database/API failures

**Features:**
- HTML-formatted emails
- Rate limiting (2-hour cooldown)
- Detailed error context

### log_cleanup.py (Maintenance)

**Purpose:** Manage log file retention.

**Features:**
- Delete logs older than 30 days
- Compress logs older than 7 days
- Always keep minimum 10 recent logs
- Runs automatically once per day

---

## Database Schema

### Supabase Tables

#### `company_data`
Stores company information for scraping.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| company | text | Company name |
| link_type | text | ATS type (green, lever, comeet, etc.) |
| unique_identifier | text | Comeet ID (nullable) |
| is_active | boolean | Whether to scrape this company |
| consecutive_failures | int | Failure counter |
| last_success | timestamp | Last successful scrape |
| last_failure | timestamp | Last failed scrape |
| last_error | text | Error message from last failure |
| total_jobs_scraped | int | Running total |

#### `scraper_log_runs`
Stores metadata from each scraper run.

| Column | Type | Description |
|--------|------|-------------|
| log_filename | text | Log file name (unique) |
| start_time | timestamp | When run started |
| end_time | timestamp | When run ended |
| duration_seconds | int | Run duration |
| companies_processed | int | Companies scraped |
| jobs_found | int | Total jobs found |
| jobs_filtered | int | Jobs matching criteria |
| error_count | int | Number of errors |
| status | text | completed/failed |

#### `emailed_jobs_history`
Tracks all jobs sent via email.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| title | text | Job title |
| company | text | Company name |
| city | text | Job location |
| link | text | Job URL |
| sent_at | timestamp | When email was sent |
| is_filtered | boolean | True if matched junior criteria |
| email_date | date | Date sent (for deduplication) |

#### `scrapers_data`
Main job data table.

| Column | Type | Description |
|--------|------|-------------|
| company | text | Company name |
| job_name | text | Job title |
| city | text | Location |
| link | text | Job URL |
| created_at | timestamp | When added |

---

## Email System

### Configuration

Email credentials are stored in `.env`:
```
Email_adddress = "nivmika@gmail.com"
Email_password = "xxxx xxxx xxxx xxxx"  # Gmail App Password
```

### Email Types

#### 1. Job Notification Email
**Trigger:** New jobs found after scraping
**Recipients:** Configured in `telegramInsertBot.py`
**Format:** HTML table with:
- Filtered jobs (matching junior criteria)
- Unfiltered jobs (may not be suitable)

#### 2. Alert Emails
**Trigger:** System issues detected
**Recipients:** `ALERT_EMAIL` from `.env`
**Types:**
- High error rate
- Company failures
- Scraper crash
- Critical errors

### Deduplication

Jobs are deduplicated daily using Supabase:
1. `get_sent_links_today()` - Get all links sent today
2. `filter_new_jobs()` - Remove already-sent jobs
3. Only new jobs are included in email

---

## LLM Integration

### LM Studio Setup

The system uses a local LLM via LM Studio for job classification.

**Server:** `http://localhost:1234/v1/chat/completions`
**Model:** `meta-llama-3.1-8b-instruct` (or similar)

### Classification Logic

The LLM analyzes job descriptions and returns:
```json
{
  "desc": "Job description summary",
  "reqs": ["requirement 1", "requirement 2"],
  "suitable_for_junior": "True" | "False" | "Unclear"
}
```

### Fallback Behavior

If LLM is unavailable:
1. Jobs with keywords (`student`, `junior`, `intern`, `entry`, `graduate`) → Sent as filtered
2. Other jobs → Sent as "unfiltered" (user should review)
3. **No jobs are lost** - all new jobs are emailed

---

## Monitoring & Alerting

### Dashboard (DashboardApp)

**Access:** `http://localhost:5050`
**Remote:** Via ngrok (URL in console output)

**Features:**
- Real-time KPIs (last run, jobs found, success rate)
- Company coverage by ATS type
- Run history table
- Jobs trend chart (7 days)
- Error alerts
- Emailed jobs history
- **Analytics** tab: content insights from `desc_reqs_scrapers` (see [Analytics](#analytics-desc_reqs_scrapers))

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/dashboard` | All dashboard data |
| `/api/kpis` | Core KPIs only |
| `/api/coverage` | Company coverage stats |
| `/api/run-history` | Recent scraper runs |
| `/api/trend` | Jobs trend (7 days) |
| `/api/emailed-jobs` | Today's emailed jobs |
| `/api/emailed-jobs/by-date/<date>` | Jobs by date |
| `/api/alerts` | Active alerts |
| `/api/health` | System health check |
| `/api/analytics/overview` | Aggregates for `desc_reqs_scrapers` in a date range |
| `/api/analytics/top-companies` | Top companies by record count |
| `/api/analytics/top-titles` | Top normalized job titles |
| `/api/analytics/top-requirements` | Top requirement keywords (tokenized from `reqs`) |
| `/api/analytics/trend` | Daily record counts in range |
| `/api/analytics/companies` | Company names in range (for filters) |
| `/api/analytics/matching-jobs` | Jobs matching keyword with full `desc` and parsed `reqs` |
| `/api/cron-trigger` | Runs scraper via subprocess if interval + schedule allow |
| `/api/cron-trigger/test` | Test endpoint (sleeps 10s; verifies client waits for response) |

### Alert Thresholds

| Alert | Threshold | Cooldown |
|-------|-----------|----------|
| High Error Rate | >20% failures | 2 hours |
| Company Failures | 5+ consecutive | 2 hours |
| Auto-Deactivate | 10+ consecutive | N/A |
| No Jobs Found | 24+ hours | 2 hours |

---

## Manual Commands & Scripts

### Main Scraper

```bash
# Start the scraper (runs continuously)
cd Scrapers
python CleanScript.py

# The scraper will:
# - Start dashboard on port 5050
# - Open ngrok tunnel
# - Run every 2 hours (configurable)
```

### Database Operations

```bash
cd Scrapers

# Test database connection
python db_operations.py test-connection

# Sync companies from JSON to database
python db_operations.py sync --json-path "../airflow_processes/data/combined_company_data3.json"

# Dry run (see what would change)
python db_operations.py sync --dry-run

# Backfill log metadata from existing log files
python db_operations.py backfill-logs --logs-dir "./logs" --limit 100
```

### Log Cleanup

```bash
cd Scrapers

# Show disk usage statistics
python log_cleanup.py --stats

# Preview cleanup (dry run)
python log_cleanup.py --dry-run

# Run cleanup with defaults (30 day retention)
python log_cleanup.py

# Custom retention (keep 60 days, compress after 14)
python log_cleanup.py --retention-days 60 --compress-after-days 14

# Disable compression (delete only)
python log_cleanup.py --no-compress
```

### Alert Testing

```bash
cd Scrapers

# Test alert system
python alerting.py
# This will send a test high error rate alert
```

### Individual ATS Testing

```python
# In Python REPL or script
from CleanScript import JobScraper

scraper = JobScraper([])

# Test Greenhouse
jobs = scraper.scrape_greenhouse_jobs_api("monday")
print(jobs)

# Test Lever
jobs = scraper.fetch_lever_jobs_api("tonkean")
print(jobs)

# Test BambooHR
jobs = scraper.scrape_bamboohr_jobs_api("solitics")
print(jobs)

# Test Ashby
jobs = scraper.scrape_ashby_jobs_api("companyname")
print(jobs)

# Test Comeet
from comeet_scraper import test_comeet_company
jobs = test_comeet_company("monday", "41.00B")
print(jobs)
```

### Database Migrations

```sql
-- Run in Supabase SQL Editor

-- Create tables (if needed)
\i migrations/001_create_company_and_log_tables.sql

-- Add failure tracking columns
\i migrations/002_add_failure_tracking.sql

-- View companies with issues
SELECT * FROM companies_with_issues;

-- Reset all company failures (maintenance)
SELECT reset_all_company_failures();
```

### Manual Email Test

```python
# In Python REPL
from telegramInsertBot import SendEmail

test_jobs = [
    ['Software Engineer', 'TestCompany', 'Tel Aviv', 'https://example.com/job1'],
    ['Junior Developer', 'AnotherCo', 'Herzliya', 'https://example.com/job2']
]

SendEmail(test_jobs, test_jobs, [], [])
```

---

## Configuration

### Environment Variables (.env)

```bash
# Database
supabaseUrl = "https://xxx.supabase.co"
supabaseKey = "your-key"

# Email
Email_adddress = "your@email.com"
Email_password = "app-password"

# Telegram (optional)
TELEGRAM_BOT_TOKEN = "your-token"
channel_id2 = "-1234567890"

# Schedule
SCRAPER_START_HOUR = 08:00    # Start time (24h format)
SCRAPER_END_HOUR = 22:30      # End time
SCRAPER_SKIP_DAYS = 5         # 5 = Saturday (0=Mon, 6=Sun)
SCRAPER_SLEEP_INTERVAL = 7200 # Seconds between runs

# Alerting
ALERT_ERROR_RATE_THRESHOLD = 0.2
ALERT_CONSECUTIVE_FAILURE_THRESHOLD = 5
ALERT_AUTO_DEACTIVATE_THRESHOLD = 10
ALERT_COOLDOWN_HOURS = 2

# Log Cleanup
LOG_RETENTION_DAYS = 30
LOG_COMPRESS_AFTER_DAYS = 7
LOG_MIN_KEEP = 10
```

---

## Troubleshooting

### Common Issues

#### 1. "No jobs found" but scraper ran
- Check if within schedule hours
- Verify company data exists in DB
- Check log file for errors
- Ensure ATS APIs are accessible

#### 2. LLM classification failing
- Ensure LM Studio is running on port 1234
- Check model is loaded in LM Studio
- Fallback will still send jobs (as unclassified)

#### 3. Email not sending
- Verify Gmail App Password is correct
- Check `Email_adddress` spelling in .env
- Look for SMTP errors in logs

#### 4. Company always failing
- Check if company URL changed
- Verify LinkType is correct
- Try manual test with scraper function
- Consider deactivating if consistently broken

#### 5. "'dict' object has no attribute 'lower'" error
This was a bug in older versions where API-based scrapers (Lever, BambooHR) returned dicts but the code expected strings.
**Fixed in current version** - all API scrapers now correctly handle dict-based job data.

#### 6. "cannot unpack non-iterable NoneType object" error
This was caused by scrapers returning `None` or a single value instead of a tuple.
**Fixed in current version** - all scrapers now consistently return `(jobs_list, [])` tuples.

#### 7. Lever company returning 404
The Lever API is case-sensitive and some companies use EU instead of US API.
**Auto-handled**: The scraper now automatically:
- Tries lowercase company name if original fails
- Tries EU API if US API returns 404
- No manual configuration needed

#### 8. ChromeDriver version mismatch
**Symptom**: `session not created: This version of ChromeDriver only supports Chrome version X`
**Fixed**: The scraper now uses `webdriver-manager` to auto-download the correct ChromeDriver version.
If issues persist:
```bash
pip install --upgrade webdriver-manager
```

#### 9. Invalid company data in database
**Symptom**: Entries like `/embed/job_board?for=sisense` or `link_type: other`
**Fixed**: The scraper now validates company names and skips:
- Entries that look like URLs (contain `/`, `?`, `http`)
- Unsupported link_types (only valid types are: green, smart, lever, comeet, bamboohr, ashby, workday, icims, jobvite)

To fix bad data in Supabase:
```sql
-- Find bad entries
SELECT * FROM company_data WHERE company LIKE '%/%' OR company LIKE '%?%' OR link_type = 'other';

-- Delete or fix them
DELETE FROM company_data WHERE link_type = 'other';
UPDATE company_data SET company = 'sisense' WHERE company LIKE '%sisense%' AND company != 'sisense';
```

#### 10. Dashboard not loading
- Check if CleanScript.py is running
- Verify port 5050 is not in use
- Check Flask console for errors

### Log Analysis

```bash
# Find recent errors
grep -i "error" Scrapers/logs/scraper_*.log | tail -50

# Count companies processed in last run
grep "Processing" Scrapers/logs/scraper_$(date +%d_%m_%Y)*.log | wc -l

# Find specific company issues
grep "monday" Scrapers/logs/scraper_*.log | grep -i error
```

### Reset Procedures

```python
# Reset specific company failures
from db_operations import reset_company_failures
reset_company_failures("monday", "comeet")

# Clear today's sent emails (for re-testing)
# In Supabase: DELETE FROM emailed_jobs_history WHERE email_date = '2026-01-24';
```

---

## Analytics (desc_reqs_scrapers)

The dashboard includes an **Analytics** page that reads from Supabase table `desc_reqs_scrapers` (LLM-enriched job descriptions and requirements).

### UI (Dashboard)

1. Run the dashboard: `python DashboardApp/app.py` (default port **5050**), or use your deployed URL.
2. Open **Analytics** in the sidebar.
3. Set **Start date** and **End date** (defaults: last 30 days).
4. Optional **Companies**: comma-separated names (e.g. `monday,wix`).
5. Optional **Keyword**: filters rows where the keyword appears in company, title, description, or requirements text.
6. Click **Apply**.

You will see:

- KPI cards: total records, unique companies, unique titles, rows with non-empty requirements.
- **Records trend** chart (daily counts).
- Tables: top companies, top job titles, top requirement keywords (words extracted from parsed `reqs`).
- **Matching Jobs (Desc + Reqs)**: when a **keyword** is set, lists matching jobs with full `desc`, parsed `reqs` as text, and link. If no keyword is set, this section prompts you to add one.

### Query parameters (all analytics routes)

Shared query string (optional unless noted):

| Parameter | Description |
|-----------|-------------|
| `start` | Start date `YYYY-MM-DD` (default: 30 days ago) |
| `end` | End date `YYYY-MM-DD` (default: today) |
| `companies` | Comma-separated company names (matches `Company` column) |
| `keyword` | Substring match across company, title, `desc`, and `reqs` (where applicable) |

`limit` is supported on top-N endpoints (capped server-side).

### Server behavior

- Rows are loaded from `desc_reqs_scrapers` with `created_at` in `[start, end+1 day)` (UTC).
- **`reqs`** may be stored as a JSON list string, a plain list, or newline/bullet text; the server normalizes before tokenizing for “top requirements”.
- **`ANALYTICS_MAX_ROWS`**: max rows fetched per analytics request (default **5000**). Increase only if needed; large ranges can be slow.

### Client script (cron calling the dashboard URL)

`Scrapers/call_cron_trigger.py` uses **requests** to `GET` the cron-trigger URL and wait for the HTTP response (so the job does not exit before the server finishes).

```bash
cd Scrapers
python call_cron_trigger.py
# Test mode (server sleeps 10 seconds — verifies waiting for response):
python call_cron_trigger.py --test
```

Optional env: **`CRON_TRIGGER_URL`** — base URL of the dashboard (default `https://open-jobs-web-backend.onrender.com`).

---

## Cron job & HTTP trigger

There are two ways to run the scraper on a schedule; both respect **minimum interval** and **working-hours schedule** when implemented.

### A) Render Cron Job: run `CleanScript.py` directly

- **Schedule** (example): every 13 minutes between 08:00–22:59 UTC: `*/13 8-22 * * *`
- **Command** (example): `cd Scrapers && python CleanScript.py`
- Set **`RUN_MODE=cron`** on that service.
- **`SCRAPER_MIN_INTERVAL_MINUTES`** (default **110** = 1h50): if the last run in `scraper_log_runs` was more recent than this, the process exits without scraping.
- Schedule window uses **`SCRAPER_START_HOUR`**, **`SCRAPER_END_HOUR`**, **`SCRAPER_SKIP_DAYS`** (same as local loop mode).

### B) HTTP: ping the dashboard so the web service runs the scraper

- **Schedule**: same cron expression as above.
- **Command**: `python Scrapers/call_cron_trigger.py` (or `curl` to `/api/cron-trigger`) so the **dashboard** receives the request.
- **`GET /api/cron-trigger`**: checks last run vs **`SCRAPER_MIN_INTERVAL_MINUTES`**, checks schedule, then runs **`CleanScript.py` in a subprocess** (no heavy import of the scraper inside Flask). The HTTP request waits until the subprocess finishes (long timeout).
- **`GET /api/cron-trigger/test`**: sleeps 10 seconds then returns JSON — use to verify the client waits for a response.

**Render UI:** put only the cron expression in **Schedule** (e.g. `*/13 8-22 * * *`). Put `curl` or `python .../call_cron_trigger.py` in **Command**, not in the schedule field.

### Environment variables (relevant)

| Variable | Role |
|----------|------|
| `RUN_MODE` | `local` = loop + dashboard in CleanScript; `cron` = single run then exit |
| `SCRAPER_MIN_INTERVAL_MINUTES` | Minimum minutes between full scrapes (default 110) |
| `SCRAPER_START_HOUR` / `SCRAPER_END_HOUR` / `SCRAPER_SKIP_DAYS` | Allowed scrape window |
| `PROJECT_ROOT` | Repo root on Render (set for subprocess scraper) |
| `ANALYTICS_MAX_ROWS` | Cap for analytics queries (default 5000) |


