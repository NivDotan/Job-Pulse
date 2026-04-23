"""
Test LLM Classification & Backfill desc_reqs_scrapers table
-------------------------------------------------------------
This script:
1. Tests the LLM (Groq) connection with a sample job description
2. Fetches recent jobs from scrapers_data that are missing from desc_reqs_scrapers
3. Classifies them via LLM and inserts results into desc_reqs_scrapers

Usage:
    cd Scrapers
    python test_llm_and_backfill.py --test          # Test LLM only
    python test_llm_and_backfill.py --backfill       # Backfill missing jobs
    python test_llm_and_backfill.py --backfill --dry  # Preview what would be backfilled
"""

import os
import sys
import json
import argparse
import time
from os.path import join, dirname
from dotenv import load_dotenv

# Load environment variables
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

import supabase
import requests
from bs4 import BeautifulSoup
import html as html_module
import re
import local_llm_function


# ============================================
# Database Connection
# ============================================

def get_db():
    supabase_url = os.environ.get("supabaseUrl")
    supabase_key = os.environ.get("supabaseKey")
    return supabase.create_client(supabase_url, supabase_key)


# ============================================
# TEST: Verify LLM connection works
# ============================================

def test_llm():
    """Test the LLM with a sample job description."""
    print("=" * 60)
    print("TEST: LLM Connection & Classification")
    print("=" * 60)
    
    # Print config
    print(f"  API URL:  {local_llm_function.LLM_API_URL}")
    print(f"  Model:    {local_llm_function.LLM_MODEL}")
    print(f"  API Key:  {'***' + local_llm_function.LLM_API_KEY[-6:] if local_llm_function.LLM_API_KEY else 'NOT SET'}")
    print()
    
    sample_text = """
    Junior Software Developer
    
    About the Role:
    We are looking for a Junior Software Developer to join our engineering team.
    You will work on building and maintaining web applications using modern technologies.
    
    Responsibilities:
    - Write clean, maintainable code
    - Participate in code reviews
    - Collaborate with the team on new features
    - Fix bugs and improve performance
    
    Requirements:
    - BSc in Computer Science or equivalent
    - Knowledge of Python or JavaScript
    - Understanding of web development fundamentals
    - Good communication skills
    - 0-1 years of experience
    """
    
    print("Sending sample job description to LLM...")
    print("-" * 40)
    
    try:
        result = local_llm_function.classify_job_for_juniors(sample_text)
        print("-" * 40)
        
        # Parse the result
        parsed = json.loads(result)
        print(f"\n  desc:               {parsed.get('desc', 'N/A')[:80]}...")
        print(f"  reqs:               {parsed.get('reqs', [])}")
        print(f"  suitable_for_junior: {parsed.get('suitable_for_junior', 'N/A')}")
        print(f"\n  TEST PASSED" if parsed.get('suitable_for_junior') in ['True', 'False', 'Unclear'] else "\n  TEST FAILED: unexpected suitable_for_junior value")
        return True
    except Exception as e:
        print(f"\n  TEST FAILED: {e}")
        return False


# ============================================
# Fetch job description from career pages
# ============================================

def get_data_from_comeet(url):
    """Extract job description from Comeet page and classify with LLM."""
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"  Failed to fetch page (status {response.status_code})")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        page_text = response.text
        job_data = None

        # 1. Try JSON-LD
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

        # 2. Fallback: POSITION_DATA
        if job_data is None:
            match = re.search(r"POSITION_DATA\s*=\s*(\{.*?\});", page_text, re.DOTALL)
            if match:
                try:
                    js_obj = match.group(1).rstrip(";")
                    job_data = json.loads(js_obj)
                except Exception:
                    pass

        # 3. Fallback: <h1>
        if job_data is None:
            h1 = soup.find("h1")
            job_data = {"title": h1.get_text(strip=True)} if h1 else {}

        # Extract description
        raw_desc = job_data.get("description", "")
        if not raw_desc and "custom_fields" in job_data:
            try:
                details = job_data.get("custom_fields", {}).get("details", [])
                desc_parts = []
                for field in details:
                    if field.get("name") and field.get("value"):
                        desc_parts.append(f"{field.get('name')}\n{field.get('value')}")
                if desc_parts:
                    raw_desc = "\n\n".join(desc_parts)
            except Exception:
                pass

        if raw_desc:
            decoded_html = html_module.unescape(raw_desc)
            clean_text = BeautifulSoup(decoded_html, "html.parser").get_text()
        else:
            clean_text = "No description found."

        result = local_llm_function.classify_job_for_juniors(clean_text)
        return json.loads(result)

    except Exception as e:
        print(f"  Error: {e}")
        return None


def get_data_from_greenhouse(url):
    """Extract job description from Greenhouse page and classify with LLM."""
    try:
        response = requests.get(url, timeout=15)
        txt = response.text

        pattern = (
            r'window\.__remixContext\s*=\s*{.*?"state"\s*:\s*{.*?"loaderData"\s*:\s*{.*?'
            r'"routes/\$url_token_\.jobs_\.\$job_post_id"\s*:\s*{.*?"jobPost"\s*:\s*{.*?"content"\s*:\s*("(?:\\.|[^"\\])*")'
            r'.*?}.*?}.*?}.*?};\n'
        )
        match = re.search(pattern, txt, re.DOTALL)
        if match:
            js_obj_str = match.group(1)
            decoded_unicode = js_obj_str.encode('utf-8').decode('unicode_escape')
            clean_html = html_module.unescape(decoded_unicode)
            soup = BeautifulSoup(clean_html, "html.parser")
            plain_text = soup.get_text(separator="").strip()

            result = local_llm_function.classify_job_for_juniors(plain_text)
            return json.loads(result)
        else:
            print("  Could not extract content from Greenhouse page")
            return None

    except Exception as e:
        print(f"  Error: {e}")
        return None


# ============================================
# BACKFILL: Process jobs missing from desc_reqs_scrapers
# ============================================

def get_missing_jobs():
    """
    Find jobs in scrapers_data that don't have entries in desc_reqs_scrapers.
    Only returns Comeet and Greenhouse jobs (the ones we can extract descriptions from).
    """
    conn = get_db()
    
    # Get all links already in desc_reqs_scrapers
    print("Fetching existing desc_reqs_scrapers entries...")
    existing = conn.table("desc_reqs_scrapers").select("Link").execute()
    existing_links = set(row["Link"] for row in existing.data) if existing.data else set()
    print(f"  Found {len(existing_links)} existing entries")
    
    # Get all jobs from scrapers_data
    print("Fetching scrapers_data entries...")
    all_jobs = conn.table("scrapers_data").select("*").execute()
    all_jobs_data = all_jobs.data if all_jobs.data else []
    print(f"  Found {len(all_jobs_data)} total jobs")
    
    # Filter: only comeet/greenhouse links that are NOT already in desc_reqs
    missing = []
    for job in all_jobs_data:
        link = job.get("link", "")
        if link and link not in existing_links:
            if "comeet" in link or "green" in link or "greenhouse" in link:
                missing.append(job)
    
    print(f"  Found {len(missing)} jobs missing from desc_reqs_scrapers (comeet/greenhouse)")
    return missing


def backfill(dry_run=False):
    """Backfill desc_reqs_scrapers for jobs that are missing LLM classification."""
    print("=" * 60)
    print(f"BACKFILL: desc_reqs_scrapers {'(DRY RUN)' if dry_run else ''}")
    print("=" * 60)
    
    missing = get_missing_jobs()
    
    if not missing:
        print("\nNo jobs to backfill. All scrapers_data entries already have desc_reqs.")
        return
    
    print(f"\nProcessing {len(missing)} jobs...")
    print("-" * 60)
    
    conn = get_db()
    success_count = 0
    fail_count = 0
    
    for i, job in enumerate(missing, 1):
        company = job.get("company", "Unknown")
        job_name = job.get("job_name", "Unknown")
        link = job.get("link", "")
        city = job.get("city", "Unknown")
        
        print(f"\n[{i}/{len(missing)}] {company} - {job_name}")
        print(f"  Link: {link}")
        
        if dry_run:
            print(f"  [DRY RUN] Would process this job")
            continue
        
        reqs_desc = None
        try:
            if "comeet" in link:
                reqs_desc = get_data_from_comeet(link)
            elif "green" in link or "greenhouse" in link:
                reqs_desc = get_data_from_greenhouse(link)
        except Exception as e:
            print(f"  Error fetching: {e}")
        
        if reqs_desc and isinstance(reqs_desc, dict):
            try:
                data = {
                    "desc": reqs_desc.get("desc", ""),
                    "reqs": reqs_desc.get("reqs", ""),
                    "Company": company,
                    "JobDesc": job_name,
                    "Link": link
                }
                conn.table("desc_reqs_scrapers").insert(data).execute()
                print(f"  Saved to DB (suitable_for_junior: {reqs_desc.get('suitable_for_junior', 'N/A')})")
                success_count += 1
            except Exception as e:
                print(f"  DB insert error: {e}")
                fail_count += 1
        else:
            print(f"  Could not extract description")
            fail_count += 1
        
        # Rate limit: Groq free tier is 30 req/min
        time.sleep(2.5)
    
    print("\n" + "=" * 60)
    print(f"BACKFILL COMPLETE: {success_count} succeeded, {fail_count} failed out of {len(missing)} jobs")
    print("=" * 60)


# ============================================
# Main
# ============================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test LLM & backfill desc_reqs_scrapers")
    parser.add_argument("--test", action="store_true", help="Test LLM connection with sample data")
    parser.add_argument("--backfill", action="store_true", help="Backfill missing jobs in desc_reqs_scrapers")
    parser.add_argument("--dry", action="store_true", help="Dry run (preview only, no DB writes)")
    
    args = parser.parse_args()
    
    if not args.test and not args.backfill:
        # Default: run test
        print("No flags specified. Running --test by default.\n")
        args.test = True
    
    if args.test:
        test_llm()
    
    if args.backfill:
        backfill(dry_run=args.dry)
