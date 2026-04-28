# Scraper Scheduling System

## Overview

The scraper runs on a single Render cron job that fires every 2 hours.
Instead of always scraping everything, a `scraper_schedule` table in Supabase
decides **which job** runs on each tick — each job has its own interval and
last-run timestamp.

---

## The Three Jobs

| Job | ATS Systems | Location Filter | Interval | Fires ~N times/day |
|---|---|---|---|---|
| `regular_ats` | Greenhouse, Lever, Comeet, BambooHR, Ashby, Workday | Israeli / IL only | 110 min | ~7× |
| `new_ats` | iCIMS, Jobvite | Israeli / IL only | 660 min | 2× |
| `usa_digest` | All of the above | USA only + send email | 1380 min | 1× |

### Why this split?

- **`regular_ats`** — The core Israeli pipeline. Runs frequently so new Israeli
  jobs reach the inbox quickly.
- **`new_ats`** — iCIMS and Jobvite are newer/less-tested ATS platforms. Running
  them twice a day reduces noise and load while still catching daily postings.
- **`usa_digest`** — Scrapes all companies once a day, keeps only US-located
  jobs, and immediately sends the nightly digest email. US jobs don't need
  real-time delivery, so once a day is enough.

---

## The `scraper_schedule` Table

Created by `migrations/003_scraper_schedule.sql`.

```
job_name         TEXT  PRIMARY KEY
description      TEXT
min_interval_min INT               -- interval between runs in minutes
last_run_at      TIMESTAMPTZ       -- when the last run started
next_run_at      TIMESTAMPTZ       -- earliest time the job may run again
last_status      TEXT              -- idle | running | completed | failed
last_jobs_found  INT               -- jobs found in the last run
is_enabled       BOOLEAN
updated_at       TIMESTAMPTZ
```

`next_run_at` is advanced by `min_interval_min` the moment a job starts
(inside `set_job_running()`), not when it finishes. This prevents a second
cron tick from spawning the same job while it is still running.

---

## What Happens on Each Cron Tick

```
Render cron fires (every 2h, 08:00–22:00 UTC, skips Saturday)
  │
  ├── is_within_schedule()? → No  → exit (nothing runs)
  │
  └── Yes
        │
        └── get_due_jobs()
              queries: next_run_at <= NOW() AND is_enabled = TRUE
                       AND last_status != 'running'
              │
              ├── [] (nothing due) → exit
              │
              └── [job_name, ...]
                    for each due job (serially — shared tmp files):
                      set_job_running(job)     ← advances next_run_at immediately
                      run CleanScript.py --job <job>
                      update_job_schedule(job, status, jobs_found)
```

### Concrete example

Table state at 09:45 UTC on 2026-04-28:

| job_name | next_run_at | Due? |
|---|---|---|
| regular_ats | 2026-04-28 09:40 | **Yes** |
| new_ats | 2026-04-29 19:00 | No |
| usa_digest | 2026-04-29 17:00 | No |

→ Only `regular_ats` runs. Its `next_run_at` is set to `09:45 + 110min = 11:35`
before scraping starts. The 11:00 tick finds nothing due; the 12:00 tick runs
`regular_ats` again.

---

## Location Filtering per Job

Each job applies a different location filter inside `telegramInsertBot.py`:

| Job | Filter | Effect |
|---|---|---|
| `regular_ats` | `israel_only` | Only jobs with Israeli city / "IL" / "Israel" in location reach the email |
| `new_ats` | `israel_only` | Same |
| `usa_digest` | `usa_only` | Only US-located jobs are collected; `scrapers_data` is NOT updated; `send_us_jobs_digest()` is called immediately after saving to `us_jobs_history` |

A company can have both Israeli and US job postings. The filter operates at the
**job level**, not the company level — the same company may appear in both a
`regular_ats` run (its Israeli openings) and a `usa_digest` run (its US
openings).

---

## Render Cron Configuration

No changes needed from the original setup:

```
Schedule : 0 8-22/2 * * *          (every 2h, 08:00–22:00 UTC)
Command  : cd Scrapers && python CleanScript.py
```

`CleanScript.py` called without `--job` queries `get_due_jobs()` itself and
runs each due job in sequence.

The `--job` flag exists for manual runs and for when `app.py`'s
`/api/cron-trigger` endpoint spawns individual jobs directly:

```bash
python CleanScript.py --job regular_ats
python CleanScript.py --job new_ats
python CleanScript.py --job usa_digest
```

---

## Setting the Initial usa_digest Time

After running the migration, all three jobs have `next_run_at = NOW()` and will
fire on the very first cron tick. If you want the USA digest to always go out at
a specific time (e.g. 8 PM Israel = 5 PM UTC), update it once in Supabase:

```sql
UPDATE scraper_schedule
SET next_run_at = '2026-04-29 17:00:00+00'
WHERE job_name = 'usa_digest';
```

After that first run it will self-schedule at the same offset every ~23 hours.

---

## Key Files Changed

| File | What changed |
|---|---|
| `migrations/003_scraper_schedule.sql` | Creates `scraper_schedule` table |
| `Scrapers/db_operations.py` | `get_companies_by_job_type`, `get_due_jobs`, `set_job_running`, `update_job_schedule` |
| `Scrapers/CleanScript.py` | `run_scraper_once(job_type)`, `--job` arg, schedule-driven loop |
| `Scrapers/telegramInsertBot.py` | `is_location_in_usa()`, `location_filter` param on `process_jobs2` and `main` |
| `DashboardApp/app.py` | `/api/cron-trigger` now reads `scraper_schedule` and spawns per-job |
