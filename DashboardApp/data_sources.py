"""
Data access layer for the dashboard.

Provides DB-backed query functions with automatic filesystem fallback
for local development. All public functions are called by app.py routes.
"""
import os
import re
import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict, Counter

from dotenv import load_dotenv

from supabase_client import get_supabase_connection

# ── Config ──────────────────────────────────────────────────────────────────

RUN_MODE = os.environ.get("RUN_MODE", "local")
IS_RENDER = RUN_MODE in ("cron", "render") or os.environ.get("RENDER", "") == "true"

if not IS_RENDER:
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Scrapers", ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
else:
    load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "Scrapers", "logs")
COMPANY_DATA_PATH = os.path.join(BASE_DIR, "airflow_processes", "data", "combined_company_data3.json")
DEDUPED_OUTPUT_PATH = os.path.join(BASE_DIR, "deduplicated_links_for_bot.json")

USE_DATABASE = True

try:
    from db_operations import (
        get_all_companies as db_get_all_companies,
        get_recent_log_runs,
        get_latest_log_run,
        get_jobs_trend_from_db,
        get_company_coverage_from_db
    )
    DB_OPERATIONS_AVAILABLE = True
except ImportError as e:
    DB_OPERATIONS_AVAILABLE = False
    print(f"Warning: Could not import db_operations module: {e}")
    db_get_all_companies = lambda: []
    get_recent_log_runs = lambda limit=15: []
    get_latest_log_run = lambda: None
    get_jobs_trend_from_db = lambda days=7: []
    get_company_coverage_from_db = lambda: {}


# ── DB-backed functions ──────────────────────────────────────────────────────

def get_log_runs_from_db(limit=15):
    """Get log run data from database."""
    if not DB_OPERATIONS_AVAILABLE or not USE_DATABASE:
        return None

    try:
        return get_recent_log_runs(limit=limit)
    except Exception as e:
        print(f"Error fetching log runs from DB: {e}")
        return None


def get_company_data_from_db():
    """Get company data from database."""
    if not DB_OPERATIONS_AVAILABLE or not USE_DATABASE:
        return None

    try:
        return db_get_all_companies()
    except Exception as e:
        print(f"Error fetching company data from DB: {e}")
        return None


def get_core_kpis_from_db():
    """Get core KPIs from database. Returns None if DB unavailable."""
    if not DB_OPERATIONS_AVAILABLE or not USE_DATABASE:
        return None

    try:
        latest_run = get_latest_log_run()

        if not latest_run:
            return None

        kpis = {
            "last_run_time": None,
            "run_duration": None,
            "companies_processed": 0,
            "companies_with_results": 0,
            "jobs_found_today": 0,
            "jobs_passed_filter": 0,
            "last_email_time": None,
            "email_count": 0,
            "cycle_state": "idle",
            "last_error": None,
            "success_rate": 0,
        }

        if latest_run.get("start_time"):
            kpis["last_run_time"] = latest_run["start_time"][:19].replace("T", " ")

        if latest_run.get("duration_seconds"):
            secs = latest_run["duration_seconds"]
            mins, secs = divmod(secs, 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                kpis["run_duration"] = f"{hours}h {mins}m {secs}s"
            elif mins > 0:
                kpis["run_duration"] = f"{mins}m {secs}s"
            else:
                kpis["run_duration"] = f"{secs}s"

        kpis["companies_processed"] = latest_run.get("companies_processed", 0) or 0
        kpis["jobs_found_today"] = latest_run.get("jobs_found", 0) or 0
        kpis["jobs_passed_filter"] = latest_run.get("jobs_filtered", 0) or 0
        kpis["error_count"] = latest_run.get("error_count", 0) or 0

        error_count = latest_run.get("error_count", 0) or 0
        processed = kpis["companies_processed"]
        kpis["companies_with_results"] = max(0, processed - error_count) if processed else 0

        error_summary = latest_run.get("error_summary", [])
        if error_summary and isinstance(error_summary, list) and len(error_summary) > 0:
            kpis["last_error"] = error_summary[0]

        recent_runs = get_recent_log_runs(limit=10)
        successful_runs = 0
        for run in recent_runs:
            run_errors = run.get("error_count", 0) or 0
            run_companies = run.get("companies_processed", 0) or 0
            if run_companies > 0:
                error_ratio = run_errors / run_companies
                if error_ratio < 0.2:
                    successful_runs += 1
            elif run.get("jobs_filtered", 0) and run.get("jobs_filtered", 0) > 0:
                successful_runs += 1

        if recent_runs:
            kpis["success_rate"] = round((successful_runs / len(recent_runs)) * 100, 1)

        if kpis["success_rate"] >= 80:
            kpis["cycle_state"] = "completed"
        elif latest_run.get("status") == "failed":
            kpis["cycle_state"] = "failed"
        else:
            kpis["cycle_state"] = "idle"

        return kpis

    except Exception as e:
        print(f"Error getting KPIs from DB: {e}")
        return None


def get_run_history_from_db(limit=15):
    """Get run history from database formatted for the dashboard."""
    if not DB_OPERATIONS_AVAILABLE or not USE_DATABASE:
        return None

    try:
        runs = get_recent_log_runs(limit=limit)

        history = []
        for run in runs:
            error_count = run.get("error_count", 0) or 0
            companies_processed = run.get("companies_processed", 0) or 0

            entry = {
                "log_file": run.get("log_filename", "N/A"),
                "start_time": run.get("start_time", "N/A")[:16].replace("T", " ") if run.get("start_time") else "N/A",
                "end_time": run.get("end_time", "N/A")[11:19] if run.get("end_time") else "N/A",
                "duration": f"{run.get('duration_seconds', 0)}s" if run.get("duration_seconds") else "N/A",
                "companies_scanned": companies_processed,
                "total_companies": run.get("total_companies", 0) or 0,
                "jobs_found": run.get("jobs_found", 0) or 0,
                "jobs_filtered": run.get("jobs_filtered", 0) or 0,
                "errors": error_count,
                "status": run.get("status", "unknown"),
                "error_summary": run.get("error_summary", []) or [],
                "top_locations": run.get("top_locations", {}) or {},
            }

            if companies_processed > 0 and error_count / companies_processed >= 0.2:
                entry["status"] = "warning"
            elif run.get("status") == "failed":
                entry["status"] = "failed"
            else:
                entry["status"] = "success"

            history.append(entry)

        return history

    except Exception as e:
        print(f"Error getting run history from DB: {e}")
        return None


# ── Filesystem helpers ───────────────────────────────────────────────────────

def parse_log_file(log_path):
    """Parse a single log file and extract metrics."""
    metrics = {
        "start_time": None,
        "end_time": None,
        "duration_seconds": None,
        "companies_processed": 0,
        "total_companies": 0,
        "jobs_found": 0,
        "jobs_filtered": 0,
        "errors": [],
        "warnings": [],
        "companies_with_jobs": set(),
        "ats_breakdown": defaultdict(int),
        "failed_companies": [],
        "keyword_hits": Counter(),
        "locations": Counter(),
    }

    if not os.path.exists(log_path):
        return metrics

    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return metrics

    for line in lines:
        timestamp_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        if timestamp_match:
            timestamp_str = timestamp_match.group(1)
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                if metrics["start_time"] is None:
                    metrics["start_time"] = timestamp
                metrics["end_time"] = timestamp
            except Exception:
                pass

        if "Starting the scraping process" in line:
            if metrics["start_time"] is None and timestamp_match:
                try:
                    metrics["start_time"] = datetime.strptime(timestamp_match.group(1), "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

        processing_match = re.search(r'Processing.*\[(\d+)/(\d+)\]', line)
        if processing_match:
            current = int(processing_match.group(1))
            total = int(processing_match.group(2))
            metrics["companies_processed"] = max(metrics["companies_processed"], current)
            metrics["total_companies"] = total

        ats_match = re.search(r"'LinkType':\s*'(\w+)'", line)
        if ats_match and "Processing {" in line:
            ats_type = ats_match.group(1)
            metrics["ats_breakdown"][ats_type] += 1

        jobs_match = re.search(r'Processing (\w+),(\w+), job titles: \[(.*?)\], links:', line)
        if jobs_match:
            company = jobs_match.group(1)
            try:
                jobs_str = jobs_match.group(3)
                jobs_count = jobs_str.count("'title':")
                if jobs_count > 0:
                    metrics["jobs_found"] += jobs_count
                    metrics["companies_with_jobs"].add(company)
            except Exception:
                pass

        filtered_match = re.search(r'Filtered jobs found.*?: \[(.*?)\]$', line)
        if filtered_match:
            try:
                filtered_str = filtered_match.group(1)
                filtered_count = filtered_str.count("'title':")
                metrics["jobs_filtered"] += filtered_count
            except Exception:
                pass

        loc_matches = re.findall(r"'location':\s*'([^']+)'", line)
        for loc in loc_matches:
            metrics["locations"][loc] += 1

        if " ERROR:" in line:
            error_msg = line.split(" ERROR:")[-1].strip()[:200]
            if error_msg and "Stacktrace" not in error_msg and "GetHandleVerifier" not in error_msg:
                metrics["errors"].append(error_msg)

        if " WARNING:" in line:
            warning_msg = line.split(" WARNING:")[-1].strip()[:200]
            if warning_msg and "chromedriver" not in warning_msg.lower():
                metrics["warnings"].append(warning_msg)

    if metrics["start_time"] and metrics["end_time"]:
        duration = metrics["end_time"] - metrics["start_time"]
        metrics["duration_seconds"] = int(duration.total_seconds())

    metrics["companies_with_jobs"] = len(metrics["companies_with_jobs"])
    metrics["errors"] = metrics["errors"][:20]
    metrics["warnings"] = metrics["warnings"][:10]
    metrics["ats_breakdown"] = dict(metrics["ats_breakdown"])
    metrics["locations"] = dict(metrics["locations"])
    metrics["keyword_hits"] = dict(metrics["keyword_hits"])

    return metrics


def get_log_files():
    """Get all log files sorted by modification time (newest first)."""
    if not os.path.exists(LOGS_DIR):
        return []

    log_files = glob.glob(os.path.join(LOGS_DIR, "scraper_*.log"))
    log_files.sort(key=os.path.getmtime, reverse=True)
    return log_files


def parse_log_filename(filename):
    """Extract date from log filename (format: scraper_DD_MM_YYYY_HH.log)."""
    basename = os.path.basename(filename)
    match = re.match(r'scraper_(\d{2})_(\d{2})_(\d{4})_(\d{2})\.log', basename)
    if match:
        day, month, year, hour = match.groups()
        try:
            return datetime(int(year), int(month), int(day), int(hour))
        except Exception:
            pass
    return None


# ── Public data access functions ─────────────────────────────────────────────

def get_company_data():
    """Load company data from database (with JSON file fallback)."""
    db_data = get_company_data_from_db()
    if db_data is not None:
        return db_data

    if not os.path.exists(COMPANY_DATA_PATH):
        return []

    try:
        with open(COMPANY_DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading company data: {e}")
        return []


def get_deduped_output():
    """Load deduplicated output data."""
    if not os.path.exists(DEDUPED_OUTPUT_PATH):
        return []

    try:
        with open(DEDUPED_OUTPUT_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading deduped data: {e}")
        return []


def get_core_kpis():
    """Get core KPIs for the dashboard top row (DB first, then filesystem fallback)."""
    db_kpis = get_core_kpis_from_db()
    if db_kpis is not None:
        return db_kpis

    kpis = {
        "last_run_time": None,
        "run_duration": None,
        "companies_processed": 0,
        "companies_with_results": 0,
        "jobs_found_today": 0,
        "jobs_passed_filter": 0,
        "last_email_time": None,
        "email_count": 0,
        "cycle_state": "idle",
        "last_error": None,
        "success_rate": 0,
    }

    if IS_RENDER:
        return kpis

    log_files = get_log_files()

    if log_files:
        latest_log = log_files[0]
        metrics = parse_log_file(latest_log)

        if metrics["start_time"]:
            kpis["last_run_time"] = metrics["start_time"].strftime("%Y-%m-%d %H:%M:%S")

        if metrics["duration_seconds"]:
            mins, secs = divmod(metrics["duration_seconds"], 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                kpis["run_duration"] = f"{hours}h {mins}m {secs}s"
            elif mins > 0:
                kpis["run_duration"] = f"{mins}m {secs}s"
            else:
                kpis["run_duration"] = f"{secs}s"

        kpis["companies_processed"] = metrics["companies_processed"]
        kpis["companies_with_results"] = metrics["companies_with_jobs"]
        kpis["jobs_found_today"] = metrics["jobs_found"]
        kpis["jobs_passed_filter"] = metrics["jobs_filtered"]

        if metrics["end_time"]:
            time_since_end = datetime.now() - metrics["end_time"]
            if time_since_end.total_seconds() < 300:
                kpis["cycle_state"] = "completed"
            elif metrics["errors"]:
                kpis["cycle_state"] = "failed"
            else:
                kpis["cycle_state"] = "idle"

        if metrics["errors"]:
            kpis["last_error"] = metrics["errors"][0]

    recent_logs = log_files[:10]
    successful_runs = 0
    for log_file in recent_logs:
        metrics = parse_log_file(log_file)
        if metrics["jobs_filtered"] > 0 or (metrics["companies_processed"] > 0 and len(metrics["errors"]) < 5):
            successful_runs += 1

    if recent_logs:
        kpis["success_rate"] = round((successful_runs / len(recent_logs)) * 100, 1)

    return kpis


def get_company_coverage():
    """Get company coverage statistics (DB first, then filesystem fallback)."""
    if DB_OPERATIONS_AVAILABLE and USE_DATABASE:
        try:
            db_coverage = get_company_coverage_from_db()
            if db_coverage:
                coverage = {
                    "total_companies": db_coverage.get("total_companies", 0),
                    "companies_with_listings": 0,
                    "companies_failing": 0,
                    "ats_breakdown": db_coverage.get("ats_breakdown", {})
                }

                latest_run = get_latest_log_run()
                if latest_run:
                    coverage["companies_with_listings"] = latest_run.get("companies_processed", 0) or 0
                    coverage["companies_failing"] = latest_run.get("error_count", 0) or 0

                return coverage
        except Exception as e:
            print(f"Error getting company coverage from DB: {e}")

    if IS_RENDER:
        return {"total_companies": 0, "companies_with_listings": 0, "companies_failing": 0, "ats_breakdown": {}}

    companies = get_company_data()

    coverage = {
        "total_companies": len(companies),
        "companies_with_listings": 0,
        "companies_failing": 0,
        "ats_breakdown": defaultdict(int),
    }

    for company in companies:
        ats_type = company.get("LinkType", "unknown")
        coverage["ats_breakdown"][ats_type] += 1

    log_files = get_log_files()
    if log_files:
        metrics = parse_log_file(log_files[0])
        coverage["companies_with_listings"] = metrics["companies_with_jobs"]
        coverage["companies_failing"] = len(metrics["errors"])

    coverage["ats_breakdown"] = dict(coverage["ats_breakdown"])
    return coverage


def get_filter_results():
    """Get filter result statistics (DB first, filesystem fallback for local)."""
    results = {
        "keyword_hits": {},
        "locations": {},
        "israel_jobs": 0,
        "non_israel_jobs": 0,
        "deduped_count": 0,
        "raw_count": 0,
    }

    israel_keywords = ["israel", "tel aviv", "jerusalem", "haifa", "herzliya",
                       "ramat gan", "petah tikva", "rishon", "netanya", "beer sheva",
                       "rehovot", "kfar saba", "modiin", "ashdod"]

    if DB_OPERATIONS_AVAILABLE and USE_DATABASE:
        try:
            latest_run = get_latest_log_run()
            if latest_run:
                results["raw_count"] = latest_run.get("jobs_found", 0) or 0
                results["deduped_count"] = latest_run.get("jobs_filtered", 0) or 0

                top_locations = latest_run.get("top_locations", {})
                if isinstance(top_locations, str):
                    top_locations = json.loads(top_locations)
                if top_locations:
                    results["locations"] = dict(list(top_locations.items())[:15])
                    for loc, count in top_locations.items():
                        loc_lower = loc.lower()
                        if any(kw in loc_lower for kw in israel_keywords):
                            results["israel_jobs"] += count
                        else:
                            results["non_israel_jobs"] += count

            conn = get_supabase_connection()
            if conn:
                response = conn.table("scrapers_data").select("id", count="exact").execute()
                if hasattr(response, 'count') and response.count is not None:
                    results["deduped_count"] = response.count
                elif response.data:
                    results["deduped_count"] = len(response.data)

            return results
        except Exception as e:
            print(f"Error getting filter results from DB: {e}")

    if not IS_RENDER:
        log_files = get_log_files()
        if log_files:
            metrics = parse_log_file(log_files[0])
            results["raw_count"] = metrics["jobs_found"]

            for loc, count in metrics["locations"].items():
                loc_lower = loc.lower()
                if any(kw in loc_lower for kw in israel_keywords):
                    results["israel_jobs"] += count
                else:
                    results["non_israel_jobs"] += count

            sorted_locations = sorted(metrics["locations"].items(), key=lambda x: x[1], reverse=True)[:15]
            results["locations"] = dict(sorted_locations)

        deduped = get_deduped_output()
        total_deduped = 0
        for company_data in deduped:
            if isinstance(company_data, list) and len(company_data) > 1:
                jobs = company_data[1]
                if isinstance(jobs, list):
                    total_deduped += len(jobs)
        results["deduped_count"] = total_deduped

    return results


def get_run_history(limit=15):
    """Get run history for the table (DB first, then filesystem fallback)."""
    db_history = get_run_history_from_db(limit=limit)
    if db_history is not None:
        return db_history

    if IS_RENDER:
        return []

    log_files = get_log_files()[:limit]
    history = []

    for log_file in log_files:
        metrics = parse_log_file(log_file)

        entry = {
            "log_file": os.path.basename(log_file),
            "start_time": metrics["start_time"].strftime("%Y-%m-%d %H:%M") if metrics["start_time"] else "N/A",
            "end_time": metrics["end_time"].strftime("%H:%M:%S") if metrics["end_time"] else "N/A",
            "duration": f"{metrics['duration_seconds']}s" if metrics["duration_seconds"] else "N/A",
            "companies_scanned": metrics["companies_processed"],
            "total_companies": metrics["total_companies"],
            "jobs_found": metrics["jobs_found"],
            "jobs_filtered": metrics["jobs_filtered"],
            "errors": len(metrics["errors"]),
            "status": "success" if len(metrics["errors"]) < 5 and metrics["jobs_filtered"] >= 0 else "warning" if metrics["errors"] else "failed"
        }
        history.append(entry)

    return history


def get_jobs_trend_quick(log_path):
    """Quick scan of a log file to extract just job counts (faster than full parse)."""
    jobs_found = 0
    jobs_filtered = 0

    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if "job titles:" in line:
                    jobs_found += line.count("'title':")
                elif "Filtered jobs found" in line:
                    jobs_filtered += line.count("'title':")
    except Exception:
        pass

    return jobs_found, jobs_filtered


def get_jobs_trend(days=7):
    """Get jobs found per day for trend chart (DB first, then filesystem fallback)."""
    if DB_OPERATIONS_AVAILABLE and USE_DATABASE:
        try:
            db_trend = get_jobs_trend_from_db(days=days)
            if db_trend:
                return db_trend
        except Exception as e:
            print(f"Error getting jobs trend from DB: {e}")

    if IS_RENDER:
        return [{"date": (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d"),
                 "jobs_found": 0, "jobs_filtered": 0, "runs": 0} for i in range(days - 1, -1, -1)]

    log_files = get_log_files()
    cutoff_date = datetime.now() - timedelta(days=days)
    daily_data = defaultdict(lambda: {"jobs_found": 0, "jobs_filtered": 0, "runs": 0})

    for log_file in log_files:
        log_date = parse_log_filename(log_file)
        if log_date and log_date >= cutoff_date:
            date_str = log_date.strftime("%Y-%m-%d")
            jobs_found, jobs_filtered = get_jobs_trend_quick(log_file)
            daily_data[date_str]["jobs_found"] += jobs_found
            daily_data[date_str]["jobs_filtered"] += jobs_filtered
            daily_data[date_str]["runs"] += 1

    trend = []
    for i in range(days - 1, -1, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        data = daily_data.get(date, {"jobs_found": 0, "jobs_filtered": 0, "runs": 0})
        trend.append({
            "date": date,
            "jobs_found": data["jobs_found"],
            "jobs_filtered": data["jobs_filtered"],
            "runs": data["runs"]
        })

    return trend


def get_top_companies():
    """Get top companies by job openings (DB first, filesystem fallback)."""
    company_jobs = Counter()

    if DB_OPERATIONS_AVAILABLE and USE_DATABASE:
        try:
            conn = get_supabase_connection()
            if conn:
                response = conn.table("scrapers_data").select("company").execute()
                if response.data:
                    for row in response.data:
                        company_jobs[row.get("company", "Unknown")] += 1
                    return company_jobs.most_common(10)
        except Exception as e:
            print(f"Error getting top companies from DB: {e}")

    if not IS_RENDER:
        log_files = get_log_files()
        if log_files:
            latest_log = log_files[0]
            try:
                with open(latest_log, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                pattern = r'Filtered jobs found for company \'([^\']+)\': \[(.*?)\]$'
                matches = re.findall(pattern, content, re.MULTILINE)

                for company, jobs_str in matches:
                    job_count = jobs_str.count("'title':")
                    if job_count > 0:
                        company_jobs[company] += job_count
            except Exception:
                pass

    return company_jobs.most_common(10)


def get_alerts():
    """Check for alert conditions (DB first, filesystem fallback)."""
    alerts = []

    if DB_OPERATIONS_AVAILABLE and USE_DATABASE:
        try:
            latest_run = get_latest_log_run()
            if latest_run:
                start_time = latest_run.get("start_time")
                if start_time:
                    try:
                        run_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
                        hours_since_run = (datetime.utcnow() - run_dt).total_seconds() / 3600
                        if hours_since_run > 3:
                            alerts.append({
                                "type": "warning",
                                "message": f"No run in last {int(hours_since_run)} hours"
                            })
                    except Exception:
                        pass

                error_count = latest_run.get("error_count", 0) or 0
                if error_count > 100:
                    alerts.append({
                        "type": "danger",
                        "message": f"High error count: {error_count} errors in latest run"
                    })

                if latest_run.get("status") == "failed":
                    error_summary = latest_run.get("error_summary", [])
                    msg = "Latest scraper run failed"
                    if error_summary and isinstance(error_summary, list) and len(error_summary) > 0:
                        msg += f": {error_summary[0][:100]}"
                    alerts.append({
                        "type": "danger",
                        "message": msg
                    })
            else:
                alerts.append({
                    "type": "warning",
                    "message": "No scraper runs found in database"
                })

            return alerts
        except Exception as e:
            print(f"Error getting alerts from DB: {e}")

    if not IS_RENDER:
        log_files = get_log_files()
        if log_files:
            latest_log = log_files[0]
            log_date = parse_log_filename(latest_log)

            if log_date:
                hours_since_run = (datetime.now() - log_date).total_seconds() / 3600
                if hours_since_run > 3:
                    alerts.append({
                        "type": "warning",
                        "message": f"No run in last {int(hours_since_run)} hours"
                    })

            metrics = parse_log_file(latest_log)
            if len(metrics["errors"]) > 10:
                alerts.append({
                    "type": "danger",
                    "message": f"High error count: {len(metrics['errors'])} errors in latest run"
                })

    return alerts
