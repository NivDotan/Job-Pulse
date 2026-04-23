"""
Supabase connection helper and email/job history query functions.
"""
import os
from datetime import datetime, timedelta
from collections import defaultdict

import supabase as supabase_lib


def get_supabase_connection():
    """Get Supabase client using environment credentials."""
    supabase_url = os.environ.get("supabaseUrl")
    supabase_key = os.environ.get("supabaseKey")
    if not supabase_url or not supabase_key:
        print("Warning: Supabase credentials not found in environment")
        return None
    return supabase_lib.create_client(supabase_url, supabase_key)


def get_emailed_jobs_by_date(target_date=None):
    """Get all jobs that were sent via email for a specific date from Supabase."""
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    result = {
        "date": target_date,
        "total_sent": 0,
        "filtered_count": 0,
        "unfiltered_count": 0,
        "filtered_jobs": [],
        "unfiltered_jobs": [],
        "all_jobs": []
    }

    try:
        conn = get_supabase_connection()
        if not conn:
            return result

        response = conn.table("emailed_jobs_history").select("*").eq("email_date", target_date).order("sent_at", desc=True).execute()

        if response.data:
            for job in response.data:
                job_obj = {
                    "id": job.get("id"),
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "city": job.get("city", ""),
                    "link": job.get("link", ""),
                    "sent_at": job.get("sent_at", ""),
                    "is_filtered": job.get("is_filtered", True)
                }
                result["all_jobs"].append(job_obj)

                if job.get("is_filtered", True):
                    result["filtered_jobs"].append(job_obj)
                else:
                    result["unfiltered_jobs"].append(job_obj)

            result["total_sent"] = len(result["all_jobs"])
            result["filtered_count"] = len(result["filtered_jobs"])
            result["unfiltered_count"] = len(result["unfiltered_jobs"])

    except Exception as e:
        print(f"Error loading emailed jobs from Supabase: {e}")

    return result


def get_emailed_jobs_today():
    """Get all jobs that were sent via email today."""
    return get_emailed_jobs_by_date()


def get_available_email_dates():
    """Get all distinct dates that have emailed jobs from Supabase."""
    try:
        conn = get_supabase_connection()
        if not conn:
            return []

        response = conn.table("emailed_jobs_history").select("email_date").order("email_date", desc=True).execute()

        if response.data:
            dates = list(set(row["email_date"] for row in response.data))
            dates.sort(reverse=True)
            return dates
        return []
    except Exception as e:
        print(f"Error fetching available dates from Supabase: {e}")
        return []


def get_email_history_stats():
    """Get statistics for email history (last 30 days)."""
    try:
        conn = get_supabase_connection()
        if not conn:
            return {"dates": [], "stats": {}}

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        response = conn.table("emailed_jobs_history").select("email_date, is_filtered").gte("email_date", start_date).lte("email_date", end_date).execute()

        if response.data:
            stats_by_date = defaultdict(lambda: {"total": 0, "filtered": 0, "unfiltered": 0})

            for job in response.data:
                date = job["email_date"]
                stats_by_date[date]["total"] += 1
                if job.get("is_filtered", True):
                    stats_by_date[date]["filtered"] += 1
                else:
                    stats_by_date[date]["unfiltered"] += 1

            sorted_dates = sorted(stats_by_date.keys(), reverse=True)

            return {
                "dates": sorted_dates,
                "stats": dict(stats_by_date)
            }
        return {"dates": [], "stats": {}}
    except Exception as e:
        print(f"Error fetching email history stats from Supabase: {e}")
        return {"dates": [], "stats": {}}


def get_today_jobs():
    """
    Get jobs created today from scrapers_data (UTC day window).
    Returns a list of lightweight job dicts.
    """
    jobs = []

    try:
        conn = get_supabase_connection()
        if not conn:
            return jobs

        today_utc = datetime.utcnow().date()
        today_start = datetime.combine(today_utc, datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)

        today_iso = today_start.isoformat() + "Z"
        tomorrow_iso = tomorrow_start.isoformat() + "Z"

        response = (
            conn.table("scrapers_data")
            .select("company, job_name, city, link, created_at")
            .gte("created_at", today_iso)
            .lt("created_at", tomorrow_iso)
            .order("created_at", desc=True)
            .execute()
        )

        if response.data:
            for row in response.data:
                jobs.append(
                    {
                        "company": row.get("company", ""),
                        "job_name": row.get("job_name", ""),
                        "city": row.get("city", ""),
                        "link": row.get("link", ""),
                        "created_at": row.get("created_at", ""),
                    }
                )
    except Exception as e:
        print(f"Error fetching today's jobs from scrapers_data: {e}")

    return jobs


def get_job_details_by_link(link):
    """
    Get description and requirements for a job by its link from desc_reqs_scrapers.
    """
    if not link:
        return {"has_details": False}

    try:
        conn = get_supabase_connection()
        if not conn:
            return {"has_details": False, "error": "Database unavailable"}

        response = (
            conn.table("desc_reqs_scrapers")
            .select("desc, reqs, Company, JobDesc, Link")
            .eq("Link", link)
            .limit(1)
            .execute()
        )

        rows = response.data or []
        if not rows:
            return {"has_details": False}

        row = rows[0]

        return {
            "has_details": True,
            "desc": row.get("desc", "") or "",
            "reqs": row.get("reqs", "") or "",
            "company": row.get("Company", ""),
            "job_name": row.get("JobDesc", ""),
            "link": row.get("Link", ""),
            "suitable_for_junior": row.get("suitable_for_junior"),
        }
    except Exception as e:
        print(f"Error fetching job details from desc_reqs_scrapers: {e}")
        return {"has_details": False, "error": str(e)}
