# Project Summary For Another Chat

## What this project is

This repository is an automated job aggregation system focused on junior-friendly software jobs.

Primary purpose:
- scrape many company career pages / ATS platforms
- normalize jobs into a common shape
- filter and classify jobs
- store state in Supabase
- send email digests
- expose a Flask dashboard for monitoring and admin actions

Current scope is no longer Israel-only:
- Israel jobs are the main immediate-email flow
- US jobs are also collected and sent later as a nightly digest

## High-level architecture

Main runtime path:

1. `Scrapers/CleanScript.py`
   - main orchestrator
   - loads companies from Supabase, with JSON fallback locally
   - runs scraping in a `ThreadPoolExecutor` with 6 workers
   - writes raw deduped scraper output JSON files
   - calls `telegramInsertBot.main()` for ETL + filtering + emailing
   - saves scraper-run metadata to Supabase
   - triggers alerting, log cleanup, US digest, and company discovery

2. `Scrapers/job_scrapers.py`
   - ATS adapters
   - supported ATS types in code:
     - Greenhouse
     - Lever
     - Comeet
     - BambooHR
     - Ashby
     - Workday
     - iCIMS
     - Jobvite
   - `smart` / SmartRecruiters still exists in routing but is not a modern first-class path

3. `Scrapers/telegramInsertBot.py`
   - converts raw scraped jobs into a normalized text/ETL flow
   - filters locations
   - syncs current jobs into Supabase `scrapers_data`
   - fetches job details for some job pages
   - calls the LLM to extract `desc`, `reqs`, and `suitable_for_junior`
   - sends immediate email for Israel jobs
   - stores US jobs for a nightly digest

4. `DashboardApp/app.py`
   - Flask dashboard and API
   - shows KPIs, run history, alerts, emailed jobs, today’s jobs, analytics
   - includes admin endpoints backed by Supabase JWT auth
   - exposes `GET /api/analytics/portfolio` for the portfolio AI Insights page

5. `DashboardApp/standardization.py`
   - read-time standardization layer for analysis-facing job data
   - does not mutate Supabase rows
   - normalizes companies, titles, seniority, locations, links, ATS labels, junior labels, requirements, descriptions, skills, timestamps, and statuses

6. `Scrapers/company_discovery.py`
   - separate discovery subsystem that finds new companies using supported ATSs
   - validates them and upserts them into `company_data`
   - runs automatically from `CleanScript` on a staggered schedule

## Runtime modes

`RUN_MODE=local`
- starts the Flask dashboard
- optionally opens ngrok / browser
- runs an infinite scrape loop
- respects configured schedule window

`RUN_MODE=cron`
- single run, then exits
- intended for Render cron / external trigger usage
- checks schedule window
- checks minimum interval from previous run to avoid duplicate runs

## Main data flow

### 1. Company source

Company list comes from:
- primary: Supabase `company_data`
- local fallback: `airflow_processes/data/combined_company_data3.json`

Each company record contains:
- company slug/name
- ATS type
- optional unique identifier
- for Workday, the stored unique identifier is effectively the Workday instance/base URL

### 2. Scraping

`CleanScript.JobScraper.process_job_data()`:
- validates company rows
- routes by `link_type`
- gets a list of jobs in normalized dict form like:
  - `title`
  - `location`
  - `link`
- records company success/failure in DB

### 3. Intermediate output

Scraper output is written to:
- `deduplicated_links_for_bot_unclean.json`
- `deduplicated_links_for_bot.json`

These are intermediate artifacts used by the ETL/email step.

### 4. ETL and DB sync

`telegramInsertBot.main()`:
- reads the deduped JSON
- writes a temporary text file in `Scrapers/tmp/`
- parses that into a dataframe-like ETL flow
- compares new scrape results vs existing `scrapers_data`
- inserts new jobs
- deletes jobs that disappeared from career pages

This means `scrapers_data` is treated as the current snapshot of live jobs.

### 5. Job enrichment and classification

For newly inserted jobs:
- if it can fetch description content, it runs the LLM
- the LLM returns JSON with:
  - `desc`
  - `reqs`
  - `suitable_for_junior` = `True` / `False` / `Unclear`
- that output is stored in `desc_reqs_scrapers`

LLM wrapper:
- `Scrapers/local_llm_function.py`
- currently uses Groq via the Groq SDK
- default model is `llama-3.1-8b-instant`
- exposes `build_junior_classification_prompt(raw_text)` so live Groq calls and queued batch requests use the same prompt

Fallback behavior:
- if enrichment/classification fails, jobs are still emailed
- keyword matches go to the “filtered” list
- other jobs still go out as unfiltered / fallback items

Groq batch queue:
- `Scrapers/groq_batch_queue.py`
- queues only jobs rejected by Groq quota/rate limits after clean text was extracted
- successful Groq calls still insert into `desc_reqs_scrapers`
- non-rate-limit failures are not queued
- writes Groq Batch-compatible JSONL to Supabase Storage bucket `groq-batch-requests`
- real daily files:
  - `YYYY-MM-DD/groq_batch_YYYY-MM-DD.jsonl`
  - `YYYY-MM-DD/groq_batch_YYYY-MM-DD.meta.jsonl`
- smoke files:
  - `smoke/groq_batch_storage_smoke_YYYY-MM-DD.jsonl`
  - `smoke/groq_batch_storage_smoke_YYYY-MM-DD.meta.jsonl`
- Storage append is implemented as download, dedupe by `custom_id`, and re-upload with upsert because Supabase Storage has no true append API
- smoke command: `python Scrapers/groq_batch_queue.py --smoke`
- server env needs `SUPABASE_SERVICE_ROLE_KEY` or `supabaseServiceKey`; a public bucket alone is not enough and is not recommended

### 6. Emailing

Immediate email:
- mostly Israel jobs
- sent by `telegramInsertBot.SendEmail()`
- deduplicated against `emailed_jobs_history` for the current day

Nightly US digest:
- non-Israel jobs are stored in `us_jobs_history`
- `CleanScript.run_scraper_once()` triggers `send_us_jobs_digest()` after 20:00 Israel time

## Dashboard/API

Main file:
- `DashboardApp/app.py`

Key dashboard responsibilities:
- health endpoint
- aggregate dashboard payload
- KPIs
- company coverage
- run history
- trends
- alert feed
- emailed jobs history
- today’s jobs view
- analytics over `desc_reqs_scrapers`
- portfolio analytics over `scrapers_data`, `desc_reqs_scrapers`, `emailed_jobs_history`, `company_data`, and `scraper_log_runs`

Supporting files:
- `DashboardApp/data_sources.py`
  - DB-first reads with filesystem fallback locally
- `DashboardApp/supabase_client.py`
  - emailed-jobs queries, today-jobs queries, job-detail lookup
- `DashboardApp/analytics.py`
  - aggregation over enriched job data
  - `get_portfolio_analytics()` for AI Insights portfolio data
- `DashboardApp/standardization.py`
  - read-time standardization for messy table data before analytics

Frontend:
- server-rendered Flask page + vanilla JS
- `DashboardApp/templates/index.html`
- `DashboardApp/static/js/dashboard.js`
- `DashboardApp/static/css/styles.css`

Frontend theme ("Egg"):
- warm, light, editorial theme inspired by jobs.scalefox.ai (replaced the older dark "Obsidian Gold" theme)
- off-white `#fafaf7` background, white cards, hairline borders, single teal accent `#0d9488`
- fonts: Inter (body), Raleway (headings), Instrument Serif (big stat numbers), JetBrains Mono (data)
- `styles.css` is token-driven: the whole look is controlled by the `:root` CSS variables (original var names like `--gold` were kept but now hold teal/light values)
- full reference: `DashboardApp/DESIGN.md`
- cache-bust: bump the `?v=` query string on the `<link>`/`<script>` tags in `index.html` when CSS/JS changes (currently `?v=15`)

Current AI Insights page:
- filters update automatically with no Apply button
- shows loading banner, progress track, and skeleton shimmer while new filter data loads
- focuses on Technical Demand, Requirement Blueprint, Seniority Requirement Matrix, Senior-Level Lift, technical taxonomy tables, Pipeline Snapshot, top companies, and company health
- hides/removes the previous generic KPI strip, Daily Trend, Country Breakdown, Data Quality card, Methodology block, and Standardized Job Samples table

## Database tables that matter

### Core

`company_data`
- source of truth for companies to scrape
- fields include company, link_type, unique_identifier, is_active
- also tracks failure metadata

`scraper_log_runs`
- one row per scraper run
- stores timing, counts, status, ATS breakdown, locations, error summary

`scrapers_data`
- current live jobs snapshot
- jobs inserted if newly scraped
- jobs deleted if no longer present upstream

### Emailing / enrichment

`emailed_jobs_history`
- jobs sent today / historically
- used for deduplication

`desc_reqs_scrapers`
- LLM-enriched job details
- stores description, requirements, and junior suitability
- current schema observed by analytics uses `Company`, `JobDesc`, `Link`, `created_at`, `desc`, `id`, and `reqs`
- `reqs` is commonly a JSON-list string, so `standardization.py` parses it before skill extraction

`us_jobs_history`
- stores US jobs for nightly digest

### Discovery

`discovery_state`
- tracks which ATS discovery job ran last
- used so discovery can be staggered over time

## Important files

Core backend:
- `Scrapers/CleanScript.py`
- `Scrapers/job_scrapers.py`
- `Scrapers/telegramInsertBot.py`
- `Scrapers/db_operations.py`
- `Scrapers/local_llm_function.py`
- `Scrapers/groq_batch_queue.py`
- `Scrapers/company_discovery.py`
- `Scrapers/discovery_ats.py`
- `Scrapers/discovery_search.py`
- `Scrapers/alerting.py`
- `Scrapers/schedule_manager.py`
- `Scrapers/log_cleanup.py`

Dashboard:
- `DashboardApp/app.py`
- `DashboardApp/data_sources.py`
- `DashboardApp/supabase_client.py`
- `DashboardApp/analytics.py`
- `DashboardApp/standardization.py`

Docs:
- `README.md`
- `SYSTEM_DOCUMENTATION.md`
- `Explanation.md`

Schema / migrations:
- `migrations/001_create_company_and_log_tables.sql`
- `migrations/002_add_failure_tracking.sql`

Tests:
- `Scrapers/tests/`
- `DashboardApp/tests/`

## What is covered by tests

The test suite mainly covers:
- Workday scraping behavior
- scraper routing
- location filtering
- deduplication
- keyword filtering
- LLM output shape/parsing

Tests are in:
- `Scrapers/tests/test_workday_scraper.py`
- `Scrapers/tests/test_scraper_router.py`
- `Scrapers/tests/test_location_filtering.py`
- `Scrapers/tests/test_deduplication.py`
- `Scrapers/tests/test_job_filtering.py`
- `Scrapers/tests/test_llm_classification.py`
- `Scrapers/tests/test_groq_batch_queue.py`
- `DashboardApp/tests/test_standardization.py`
- `DashboardApp/tests/test_portfolio_api.py`

Recent validation commands used for dashboard analytics work:
- `python -m py_compile DashboardApp/standardization.py DashboardApp/analytics.py DashboardApp/app.py`
- `node --check DashboardApp/static/js/dashboard.js`
- `python -m pytest DashboardApp/tests -v`
- `python -m pytest Scrapers/tests -v`

Recent validation commands used for Groq batch queue work:
- `python -m py_compile Scrapers/local_llm_function.py Scrapers/telegramInsertBot.py Scrapers/groq_batch_queue.py`
- `python -m pytest Scrapers/tests -v`
- `python Scrapers/groq_batch_queue.py --smoke`

## Practical caveats another chat should know

1. The repo mixes older and newer architecture.
   - Older ETL/text-file style logic still exists inside `telegramInsertBot.py`
   - Newer DB-first architecture exists alongside it

2. Docs are broadly accurate but not perfect.
   - Actual LLM path uses Groq in `local_llm_function.py`
   - Groq rate-limit rejections can be queued to Supabase Storage through `Scrapers/groq_batch_queue.py`

3. Admin company creation is narrower than the scraper supports.
   - `DashboardApp/app.py` admin `VALID_LINK_TYPES` only allows:
     - `green`
     - `lever`
     - `comeet`
     - `smart`
     - `bamboohr`
   - scraper code supports more ATS types than the admin UI currently allows

4. The first-stage scrape filter is broad.
   - `CleanScript` searches for a wide keyword list, not only junior jobs
   - junior suitability is decided later by the LLM/fallback logic

5. The project is operationally centered on Supabase.
   - JSON/filesystem fallbacks exist for local use
   - production behavior assumes DB availability

6. Portfolio analytics standardizes at read time.
   - Do not expect source rows in Supabase to be changed by the dashboard.
   - Soft skills such as communication, customer-facing, and problem solving are intentionally excluded from visible technical skill analytics.
   - `PORTFOLIO_ANALYTICS_MAX_ROWS` defaults to 2000 to avoid slow dashboard loads.

7. Groq batch queue uses Supabase Storage, not database rows.
   - Real queued jobs are written only when Groq hits quota/rate limits.
   - Smoke writes stay under `smoke/` and do not pollute the real daily batch file.
   - Keep `SUPABASE_SERVICE_ROLE_KEY` server-only; do not expose it in dashboard/browser env.
   - The bucket should be private even if local smoke testing can write to an existing public bucket with the service-role key.

## If another chat needs to modify the project, start here

If the task is scraper/runtime behavior:
- read `Scrapers/CleanScript.py`
- read `Scrapers/job_scrapers.py`
- read `Scrapers/telegramInsertBot.py`
- read `Scrapers/db_operations.py`

If the task is dashboard/API behavior:
- read `DashboardApp/app.py`
- read `DashboardApp/data_sources.py`
- read `DashboardApp/supabase_client.py`
- read `DashboardApp/analytics.py`
- read `DashboardApp/standardization.py`

If the task is adding new ATS/company discovery:
- read `Scrapers/company_discovery.py`
- read `Scrapers/discovery_ats.py`
- read `Scrapers/discovery_search.py`

If the task is schema/data issues:
- inspect `migrations/`
- inspect Supabase table usage in `db_operations.py` and `telegramInsertBot.py`

## One-paragraph handoff

This is a Python/Flask + Supabase job aggregation system that scrapes multiple ATS providers, syncs live jobs into Supabase, enriches some jobs with Groq-based LLM extraction/classification, emails immediate Israel-focused digests plus a nightly US digest, exposes a monitoring/admin dashboard plus a portfolio analytics AI Insights page, and includes a staggered company-discovery subsystem that finds new ATS-hosted companies and adds them to the scrape list. The main orchestrator is `Scrapers/CleanScript.py`, the ATS adapters live in `Scrapers/job_scrapers.py`, most ETL/email logic is in `Scrapers/telegramInsertBot.py`, DB operations are centralized in `Scrapers/db_operations.py`, read-time analytics standardization is in `DashboardApp/standardization.py`, and dashboard APIs live in `DashboardApp/app.py` and `DashboardApp/analytics.py`.
