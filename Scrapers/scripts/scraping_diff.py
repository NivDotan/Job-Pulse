"""
Test Scraping Differences & LLM on New Jobs
---------------------------------------------
1. compare_scrape_vs_db()   - Compare current local scrape against DB to see differences
2. show_geo_diff()          - Show which companies/jobs exist locally but not on Render (or vice versa)
3. test_llm_on_new_jobs()   - Fetch today's newly inserted jobs and run LLM classification on one

Usage:
    cd Scrapers
    python test_scraping_diff.py --compare      # Compare local scrape vs DB
    python test_scraping_diff.py --llm-new      # Run LLM on a new job from today
    python test_scraping_diff.py --all          # Run everything
"""

import os
import sys
import json
import argparse
import time
import re
from datetime import datetime, date, timedelta
from os.path import join, dirname
from collections import Counter
from dotenv import load_dotenv

dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

import supabase
import pandas as pd
import requests
from bs4 import BeautifulSoup
import html as html_module
import local_llm_function


# ============================================
# Database Connection
# ============================================

def get_db():
    supabase_url = os.environ.get("supabaseUrl")
    supabase_key = os.environ.get("supabaseKey")
    return supabase.create_client(supabase_url, supabase_key)


# ============================================
# 1. COMPARE: Local scrape vs DB
# ============================================

def compare_scrape_vs_db():
    """
    Run the same flow as the cron job: scrape companies, filter Israel,
    build df_new, then compare against df_existing from DB.
    Shows exactly what would be inserted/deleted.
    """
    print("=" * 70)
    print("COMPARE: Local scrape results vs current DB state")
    print("=" * 70)

    # --- Step 1: Get existing data from DB ---
    print("\n[1/4] Fetching existing data from scrapers_data...")
    conn = get_db()
    response = conn.table("scrapers_data").select("*").execute()
    existing_data = response.data if response.data else []
    df_existing = pd.DataFrame(existing_data)
    print(f"  DB has {len(df_existing)} rows")

    # --- Step 2: Read the current dedup JSON (from last local scrape) ---
    print("\n[2/4] Reading local dedup JSON...")
    SCRAPERS_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(SCRAPERS_DIR))
    dedup_path = os.environ.get(
        "DEDUP_JSON_PATH",
        os.path.join(PROJECT_ROOT, "deduplicated_links_for_bot_unclean.json")
    )

    if not os.path.exists(dedup_path):
        print(f"  ERROR: Dedup JSON not found at: {dedup_path}")
        print("  Run the scraper locally first to generate this file.")
        return

    with open(dedup_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # --- Step 3: Filter Israel jobs (same logic as process_jobs2) ---
    print("\n[3/4] Filtering Israel jobs from scraped data...")
    from telegramInsertBot import is_location_in_israel, clean_location

    israel_jobs = []
    total_jobs = 0
    non_israel_jobs = 0
    companies_with_jobs = Counter()
    companies_no_israel = set()

    for company_data in data:
        if len(company_data) != 2:
            continue
        company_name, jobs = company_data
        if not isinstance(jobs, list):
            continue

        if isinstance(company_name, str) and company_name.startswith("/embed/job_board?for="):
            company_name = company_name.split("=")[-1].capitalize()

        for job_entry in jobs:
            entries = []
            if isinstance(job_entry, dict):
                entries = [job_entry]
            elif isinstance(job_entry, list):
                if job_entry and all(isinstance(j, dict) for j in job_entry):
                    entries = job_entry
                elif len(job_entry) >= 3:
                    entries = [{"title": job_entry[0], "location": job_entry[1], "link": job_entry[2]}]

            for entry in entries:
                title = entry.get("title")
                location = entry.get("location", "")
                link = entry.get("link") or entry.get("url")
                total_jobs += 1

                if isinstance(location, str) and is_location_in_israel(location):
                    israel_jobs.append({
                        "company": company_name,
                        "job_name": title,
                        "city": clean_location(location) if location else location,
                        "link": link
                    })
                    companies_with_jobs[company_name] += 1
                else:
                    non_israel_jobs += 1
                    companies_no_israel.add(company_name)

    df_new = pd.DataFrame(israel_jobs)
    print(f"  Total jobs scraped: {total_jobs}")
    print(f"  Israel jobs: {len(israel_jobs)}")
    print(f"  Non-Israel jobs: {non_israel_jobs}")
    print(f"  Companies with Israel jobs: {len(companies_with_jobs)}")

    # --- Step 4: Merge and compare ---
    print("\n[4/4] Merging and comparing...")

    merge_keys = ['company', 'job_name', 'link']
    for col in merge_keys:
        if col in df_existing.columns:
            df_existing[col] = df_existing[col].astype(str).str.strip()
        if col in df_new.columns:
            df_new[col] = df_new[col].astype(str).str.strip()

    merged = df_existing.merge(df_new, on=merge_keys, how='outer', indicator=True)

    both = merged[merged['_merge'] == 'both']
    left_only = merged[merged['_merge'] == 'left_only']   # in DB, not in scrape
    right_only = merged[merged['_merge'] == 'right_only']  # in scrape, not in DB

    print(f"\n{'='*70}")
    print(f"  RESULTS:")
    print(f"  DB rows:          {len(df_existing)}")
    print(f"  Scraped rows:     {len(df_new)}")
    print(f"  Matched (both):   {len(both)}")
    print(f"  Only in DB:       {len(left_only)}  (would be DELETED)")
    print(f"  Only in scrape:   {len(right_only)}  (would be INSERTED)")
    print(f"{'='*70}")

    if len(right_only) > 0:
        print(f"\n--- NEW JOBS (would be inserted): ---")
        for _, row in right_only.head(20).iterrows():
            print(f"  + {row['company']:20s} | {row['job_name'][:50]:50s} | {row.get('city_y', row.get('city', ''))}")
        if len(right_only) > 20:
            print(f"  ... and {len(right_only) - 20} more")

    if len(left_only) > 0:
        print(f"\n--- OLD JOBS (would be deleted): ---")
        for _, row in left_only.head(20).iterrows():
            city = row.get('city_x', row.get('city', ''))
            print(f"  - {row['company']:20s} | {row['job_name'][:50]:50s} | {city}")
        if len(left_only) > 20:
            print(f"  ... and {len(left_only) - 20} more")

    # Show per-company breakdown of differences
    if len(right_only) > 0 or len(left_only) > 0:
        print(f"\n--- PER-COMPANY BREAKDOWN: ---")
        new_by_company = right_only['company'].value_counts()
        del_by_company = left_only['company'].value_counts()
        all_companies = set(new_by_company.index) | set(del_by_company.index)

        print(f"  {'Company':30s} | {'New':>5s} | {'Removed':>7s}")
        print(f"  {'-'*30}-+-{'-'*5}-+-{'-'*7}")
        for c in sorted(all_companies):
            n = new_by_company.get(c, 0)
            d = del_by_company.get(c, 0)
            print(f"  {c:30s} | {n:5d} | {d:7d}")

    return right_only, left_only


# ============================================
# 2. SHOW GEO DIFF: What Render misses vs local
# ============================================

def show_geo_diff():
    """
    Compare the LAST Render scrape (from DB created_at timestamps) vs current local scrape.
    This helps identify if geo-filtering causes different results.
    """
    print("=" * 70)
    print("GEO DIFF: Comparing Render-inserted vs locally-scraped jobs")
    print("=" * 70)

    conn = get_db()

    # Get all jobs with their created_at timestamps
    response = conn.table("scrapers_data").select("company, job_name, link, city, created_at").execute()
    all_jobs = response.data if response.data else []

    if not all_jobs:
        print("  No data in scrapers_data table.")
        return

    # Find the latest batch of inserts (same created_at timestamp = same Render cron run)
    timestamps = [j['created_at'] for j in all_jobs if j.get('created_at')]
    ts_counts = Counter(timestamps)
    most_common_ts = ts_counts.most_common(5)

    print(f"\n  Top 5 insert batches (by created_at timestamp):")
    for ts, count in most_common_ts:
        print(f"    {ts[:19]}  =>  {count} jobs")

    # Get the latest batch
    latest_ts = most_common_ts[0][0] if most_common_ts else None
    if latest_ts:
        latest_batch = [j for j in all_jobs if j.get('created_at') == latest_ts]
        print(f"\n  Latest batch ({latest_ts[:19]}): {len(latest_batch)} jobs")
        company_counts = Counter(j['company'] for j in latest_batch)
        print(f"  Companies in latest batch: {len(company_counts)}")
        for c, cnt in company_counts.most_common(10):
            print(f"    {c}: {cnt} jobs")

    print(f"\n  Total jobs in DB: {len(all_jobs)}")
    company_counts_all = Counter(j['company'] for j in all_jobs)
    print(f"  Total unique companies in DB: {len(company_counts_all)}")
    print(f"\n  Top 10 companies by job count:")
    for c, cnt in company_counts_all.most_common(10):
        print(f"    {c}: {cnt} jobs")


# ============================================
# 3. TEST LLM ON NEW JOBS: Get today's new jobs and classify one
# ============================================

def get_data_from_comeet(url):
    """Extract job description from a Comeet career page."""
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            return None, f"HTTP {response.status_code}"

        soup = BeautifulSoup(response.text, "html.parser")
        job_data = None

        # Try JSON-LD
        json_script = soup.find("script", {"type": "application/ld+json"})
        if json_script and json_script.string:
            try:
                cleaned = json_script.string.replace('\n', '').replace('\r', '').strip()
                last_brace = cleaned.rfind("}")
                if last_brace != -1:
                    cleaned = cleaned[:last_brace + 1]
                job_data = json.loads(cleaned)
            except Exception:
                pass

        # Fallback: POSITION_DATA
        if job_data is None:
            match = re.search(r"POSITION_DATA\s*=\s*(\{.*?\});", response.text, re.DOTALL)
            if match:
                try:
                    job_data = json.loads(match.group(1).rstrip(";"))
                except Exception:
                    pass

        if job_data is None:
            return None, "Could not extract job data"

        raw_desc = job_data.get("description", "")
        if not raw_desc and "custom_fields" in job_data:
            try:
                details = job_data.get("custom_fields", {}).get("details", [])
                parts = [f"{f['name']}\n{f['value']}" for f in details if f.get("name") and f.get("value")]
                raw_desc = "\n\n".join(parts)
            except Exception:
                pass

        if raw_desc:
            decoded = html_module.unescape(raw_desc)
            clean_text = BeautifulSoup(decoded, "html.parser").get_text()
        else:
            clean_text = "No description found."

        return clean_text, None
    except Exception as e:
        return None, str(e)


def get_data_from_greenhouse(url):
    """Extract job description from a Greenhouse career page."""
    try:
        response = requests.get(url, timeout=15)
        pattern = (
            r'window\.__remixContext\s*=\s*{.*?"state"\s*:\s*{.*?"loaderData"\s*:\s*{.*?'
            r'"routes/\$url_token_\.jobs_\.\$job_post_id"\s*:\s*{.*?"jobPost"\s*:\s*{.*?"content"\s*:\s*("(?:\\.|[^"\\])*")'
            r'.*?}.*?}.*?}.*?};\n'
        )
        match = re.search(pattern, response.text, re.DOTALL)
        if match:
            decoded = match.group(1).encode('utf-8').decode('unicode_escape')
            clean_html = html_module.unescape(decoded)
            soup = BeautifulSoup(clean_html, "html.parser")
            return soup.get_text(separator="").strip(), None
        else:
            return None, "Could not extract Greenhouse content"
    except Exception as e:
        return None, str(e)


def test_llm_on_new_jobs(limit=3):
    """
    Get the newest jobs inserted into scrapers_data (today or most recent),
    fetch their description from the career page, and classify with LLM.
    """
    print("=" * 70)
    print("TEST LLM: Classify newly inserted jobs")
    print("=" * 70)

    conn = get_db()

    # Get today's date range
    today = datetime.utcnow().strftime("%Y-%m-%d")
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\n  Looking for jobs created today ({today})...")
    response = conn.table("scrapers_data")\
        .select("*")\
        .gte("created_at", today)\
        .lt("created_at", tomorrow)\
        .execute()

    new_jobs = response.data if response.data else []

    # If no jobs today, get the most recent ones
    if not new_jobs:
        print(f"  No jobs created today. Getting most recent jobs...")
        response = conn.table("scrapers_data")\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
        new_jobs = response.data if response.data else []

    if not new_jobs:
        print("  No jobs found at all!")
        return

    print(f"  Found {len(new_jobs)} recent jobs")

    # Filter to only comeet/greenhouse (we can extract descriptions from these)
    processable = [j for j in new_jobs if "comeet" in j.get("link", "") or "green" in j.get("link", "")]
    print(f"  {len(processable)} have Comeet/Greenhouse links (can extract description)")

    if not processable:
        print("  No Comeet/Greenhouse jobs found among recent inserts.")
        print("  Showing recent jobs anyway:")
        for j in new_jobs[:5]:
            print(f"    {j['company']:20s} | {j['job_name'][:45]:45s} | {j.get('city', '')}")
        return

    # Process up to `limit` jobs
    jobs_to_test = processable[:limit]

    print(f"\n  Testing LLM on {len(jobs_to_test)} job(s)...")
    print("-" * 70)

    for i, job in enumerate(jobs_to_test, 1):
        company = job.get("company", "?")
        job_name = job.get("job_name", "?")
        link = job.get("link", "")
        city = job.get("city", "?")
        created = job.get("created_at", "?")[:19]

        print(f"\n[{i}/{len(jobs_to_test)}] {company} - {job_name}")
        print(f"  City: {city}")
        print(f"  Link: {link}")
        print(f"  Created: {created}")

        # Fetch description
        description = None
        error = None
        if "comeet" in link:
            description, error = get_data_from_comeet(link)
        elif "green" in link:
            description, error = get_data_from_greenhouse(link)

        if error:
            print(f"  ERROR fetching description: {error}")
            continue

        if not description:
            print(f"  Could not extract description")
            continue

        # Show a snippet of the description
        desc_preview = description[:200].replace('\n', ' ')
        print(f"  Description preview: {desc_preview}...")

        # Classify with LLM
        print(f"\n  Calling LLM (model: {local_llm_function.LLM_MODEL})...")
        try:
            result_str = local_llm_function.classify_job_for_juniors(description)
            result = json.loads(result_str)

            print(f"  ---")
            print(f"  desc:                {result.get('desc', 'N/A')[:100]}")
            reqs = result.get('reqs', [])
            if isinstance(reqs, list):
                print(f"  reqs ({len(reqs)} items):   {reqs[0][:80] if reqs else 'none'}...")
            else:
                print(f"  reqs:                {str(reqs)[:100]}")
            print(f"  suitable_for_junior: {result.get('suitable_for_junior', 'N/A')}")
            print(f"  ---")

            # Save to desc_reqs_scrapers if not already there
            existing = conn.table("desc_reqs_scrapers").select("Link").eq("Link", link).execute()
            if not existing.data:
                data = {
                    "desc": result.get("desc", ""),
                    "reqs": result.get("reqs", ""),
                    "Company": company,
                    "JobDesc": job_name,
                    "Link": link
                }
                conn.table("desc_reqs_scrapers").insert(data).execute()
                print(f"  Saved to desc_reqs_scrapers")
            else:
                print(f"  Already exists in desc_reqs_scrapers, skipped")

        except Exception as e:
            print(f"  LLM ERROR: {e}")

        # Rate limit for Groq free tier
        if i < len(jobs_to_test):
            time.sleep(3)

    print(f"\n{'='*70}")
    print("LLM test complete!")
    print(f"{'='*70}")


# ============================================
# Main
# ============================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test scraping differences & LLM on new jobs")
    parser.add_argument("--compare", action="store_true",
                        help="Compare local scrape vs DB (shows what would be inserted/deleted)")
    parser.add_argument("--geo", action="store_true",
                        help="Show DB insert batches to identify geo differences")
    parser.add_argument("--llm-new", action="store_true",
                        help="Run LLM classification on recently inserted jobs")
    parser.add_argument("--limit", type=int, default=3,
                        help="Number of jobs to test with LLM (default: 3)")
    parser.add_argument("--all", action="store_true",
                        help="Run all tests")

    args = parser.parse_args()

    if not any([args.compare, args.geo, args.llm_new, args.all]):
        print("No flags specified. Use --help for options.\n")
        print("Quick start:")
        print("  python test_scraping_diff.py --compare    # See what differs locally vs DB")
        print("  python test_scraping_diff.py --llm-new    # Test LLM on new jobs")
        print("  python test_scraping_diff.py --all        # Run everything")
        sys.exit(0)

    if args.compare or args.all:
        compare_scrape_vs_db()
        print()

    if args.geo or args.all:
        show_geo_diff()
        print()

    if args.llm_new or args.all:
        test_llm_on_new_jobs(limit=args.limit)
