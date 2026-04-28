"""
Scraper Dashboard - Monitor scraping health, data freshness, and notification output.
Based on DASHBOARD.md specification.

Data Sources:
- Primary: Database (company_data, scraper_log_runs, scrapers_data, emailed_jobs_history tables)
- Fallback: Filesystem (JSON files, log files) when running locally and DB is unavailable
"""

import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv
import jwt

app = Flask(__name__)

# Determine run mode: "local" uses filesystem fallbacks, "render" is DB-only
RUN_MODE = os.environ.get("RUN_MODE", "local")  # "local" or "cron" or "render"
IS_RENDER = RUN_MODE in ("cron", "render") or os.environ.get("RENDER", "") == "true"

if not IS_RENDER:
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Scrapers", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
else:
    load_dotenv()

from data_sources import (
    DB_OPERATIONS_AVAILABLE,
    USE_DATABASE,
    LOGS_DIR,
    COMPANY_DATA_PATH,
    DEDUPED_OUTPUT_PATH,
    get_latest_log_run,
    get_core_kpis,
    get_company_coverage,
    get_filter_results,
    get_run_history,
    get_jobs_trend,
    get_top_companies,
    get_alerts,
    get_log_files,
)
from supabase_client import (
    get_supabase_connection,
    get_emailed_jobs_by_date,
    get_emailed_jobs_today,
    get_available_email_dates,
    get_email_history_stats,
    get_today_jobs,
    get_job_details_by_link,
)
from analytics import (
    _parse_ymd_date,
    _split_csv_param,
    _normalize_text,
    _parse_reqs_field,
    _get_desc_reqs_rows,
    _analytics_overview,
    _analytics_top_companies,
    _analytics_top_titles,
    _analytics_top_requirements,
    _analytics_trend,
)

# Enable CORS for all routes
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Configuration paths - only relevant locally (Render has no filesystem data)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS_DIR = os.path.join(BASE_DIR, "Scrapers")
CLEANSCRIPT_PATH = os.path.join(SCRAPERS_DIR, "CleanScript.py")
SCRAPER_AVAILABLE = os.path.exists(CLEANSCRIPT_PATH)

# Always prefer database
print(f"RUN_MODE: {RUN_MODE}, IS_RENDER: {IS_RENDER}")
print(f"USE_DATABASE: {USE_DATABASE}, DB_OPERATIONS_AVAILABLE: {DB_OPERATIONS_AVAILABLE}")
if not IS_RENDER:
    print(f"LOGS_DIR: {LOGS_DIR} (exists: {os.path.exists(LOGS_DIR)})")
    print(f"COMPANY_DATA_PATH: {COMPANY_DATA_PATH} (exists: {os.path.exists(COMPANY_DATA_PATH)})")


# ============== Admin Auth Config ==============
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

VALID_LINK_TYPES = ("green", "lever", "comeet", "smart", "bamboohr")


def require_admin(f):
    """Decorator that verifies a Supabase JWT and checks the email matches ADMIN_EMAIL."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header.split("Bearer ", 1)[1]

        if not SUPABASE_JWT_SECRET:
            return jsonify({"error": "Server misconfigured: JWT secret not set"}), 500

        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired. Please sign in again."}), 401
        except jwt.InvalidTokenError as e:
            return jsonify({"error": f"Invalid token: {e}"}), 401

        email = payload.get("email", "")
        if not ADMIN_EMAIL or email.lower() != ADMIN_EMAIL.lower():
            return jsonify({"error": "Forbidden: you are not an admin"}), 403

        request.admin_email = email
        return f(*args, **kwargs)
    return decorated


# ============== Routes ==============

@app.route('/api/cron-trigger/test')
def api_cron_trigger_test():
    """
    Test endpoint: waits 10 seconds then returns. Use this to verify that
    the client (or browser) actually waits for the server response.
    """
    time.sleep(10)
    return jsonify({
        "status": "ok",
        "message": "Test endpoint waited 10 seconds",
        "waited_seconds": 10,
    })


@app.route('/api/cron-trigger')
def api_cron_trigger():
    """
    Single cron endpoint — called every 2 hours by Render.
    Checks the scraper_schedule table to decide which jobs are due, then
    spawns each due job as a subprocess (serially to avoid file collisions).
    """
    if not SCRAPER_AVAILABLE:
        return jsonify({
            "status": "error",
            "reason": "CleanScript.py not found (path: %s)" % CLEANSCRIPT_PATH,
        }), 500

    # ── Schedule window check (shared across all jobs) ─────────────────────
    schedule_allowed = True
    schedule_message = ""
    try:
        now_utc = datetime.utcnow()
        start_time_str = os.environ.get("SCRAPER_START_HOUR", "08:00")
        end_time_str   = os.environ.get("SCRAPER_END_HOUR",   "22:30")
        skip_days_str  = os.environ.get("SCRAPER_SKIP_DAYS",  "5")
        skip_days = [int(d.strip()) for d in skip_days_str.split(",") if d.strip()]
        if now_utc.weekday() in skip_days:
            schedule_allowed = False
            schedule_message = "Skip day"
        else:
            sh, sm = map(int, start_time_str.split(":")) if ":" in start_time_str else (8, 0)
            eh, em = map(int, end_time_str.split(":"))   if ":" in end_time_str   else (22, 30)
            now_m = now_utc.hour * 60 + now_utc.minute
            if now_m < sh * 60 + sm or now_m > eh * 60 + em:
                schedule_allowed = False
                schedule_message = "Outside schedule window"
    except Exception as e:
        print(f"Error checking schedule window: {e}")

    if not schedule_allowed:
        return jsonify({
            "status":    "skipped",
            "reason":    schedule_message or "Outside configured schedule window",
            "triggered": False,
        })

    # ── Determine which jobs are due ────────────────────────────────────────
    due_jobs = []
    try:
        sys.path.insert(0, SCRAPERS_DIR)
        from db_operations import get_due_jobs as _get_due_jobs
        due_jobs = _get_due_jobs()
    except Exception as e:
        print(f"Could not read scraper_schedule table: {e}. Falling back to regular_ats.")
        due_jobs = ["regular_ats"]

    if not due_jobs:
        return jsonify({
            "status":    "skipped",
            "reason":    "No jobs due according to scraper_schedule",
            "triggered": False,
        })

    # ── Spawn each due job serially (shared tmp files — must not overlap) ───
    import subprocess
    env = os.environ.copy()
    env["RUN_MODE"]      = "cron"
    env["PROJECT_ROOT"]  = BASE_DIR

    results = {}
    for job_name in due_jobs:
        print(f"[cron-trigger] Spawning job: {job_name}")
        try:
            proc = subprocess.run(
                [sys.executable, CLEANSCRIPT_PATH, "--job", job_name],
                cwd=SCRAPERS_DIR,
                env=env,
                timeout=7200,   # 2 h per job max
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                stderr_snippet = (proc.stderr or "")[:500]
                print(f"[cron-trigger] {job_name} exited {proc.returncode}: {stderr_snippet}")
            results[job_name] = proc.returncode
        except subprocess.TimeoutExpired:
            print(f"[cron-trigger] {job_name} timed out")
            results[job_name] = "timeout"
        except Exception as exc:
            print(f"[cron-trigger] {job_name} error: {exc}")
            results[job_name] = str(exc)

    return jsonify({
        "status":    "completed",
        "triggered": True,
        "jobs_run":  due_jobs,
        "results":   results,
    })


@app.route('/')
def index():
    """Render the main dashboard page."""
    return render_template(
        'index.html',
        supabase_url=os.environ.get("supabaseUrl", ""),
        supabase_anon_key=os.environ.get("supabaseKey", ""),
    )


@app.route('/favicon.ico')
def favicon():
    """Return empty favicon to prevent 404."""
    return '', 204


@app.route('/api/health')
def health():
    """Health check endpoint for debugging."""
    health_data = {
        "status": "ok",
        "run_mode": RUN_MODE,
        "is_render": IS_RENDER,
        "db_available": DB_OPERATIONS_AVAILABLE,
        "use_database": USE_DATABASE,
    }
    if not IS_RENDER:
        health_data["logs_dir"] = LOGS_DIR
        health_data["logs_dir_exists"] = os.path.exists(LOGS_DIR)
        health_data["company_data_exists"] = os.path.exists(COMPANY_DATA_PATH)
        health_data["deduped_output_exists"] = os.path.exists(DEDUPED_OUTPUT_PATH)
        health_data["log_files_count"] = len(get_log_files())
    return jsonify(health_data)


@app.route('/api/dashboard')
def api_dashboard():
    """API endpoint for dashboard data."""
    print("\n" + "="*50)
    print("API /api/dashboard called!")
    print("="*50)
    try:
        print("Getting KPIs...")
        kpis = get_core_kpis()
        print(f"KPIs: {kpis}")

        print("Getting company coverage...")
        company_coverage = get_company_coverage()
        print(f"Company coverage: {company_coverage}")

        print("Getting filter results...")
        filter_results = get_filter_results()
        print(f"Filter results: {filter_results}")

        print("Getting run history...")
        run_history = get_run_history()
        print(f"Run history count: {len(run_history)}")

        print("Getting jobs trend...")
        jobs_trend = get_jobs_trend()
        print(f"Jobs trend: {jobs_trend}")

        print("Getting top companies...")
        top_companies = get_top_companies()
        print(f"Top companies: {top_companies}")

        print("Getting alerts...")
        alerts = get_alerts()
        print(f"Alerts: {alerts}")

        data = {
            "kpis": kpis,
            "company_coverage": company_coverage,
            "filter_results": filter_results,
            "run_history": run_history,
            "jobs_trend": jobs_trend,
            "top_companies": top_companies,
            "alerts": alerts,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        print("="*50)
        print("API response ready!")
        print("="*50 + "\n")
        return jsonify(data)
    except Exception as e:
        print(f"ERROR in api_dashboard: {e}")
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "kpis": {"last_run_time": None, "run_duration": None, "companies_processed": 0,
                     "companies_with_results": 0, "jobs_found_today": 0, "jobs_passed_filter": 0,
                     "cycle_state": "failed", "success_rate": 0},
            "company_coverage": {"total_companies": 0, "companies_with_listings": 0, "companies_failing": 0, "ats_breakdown": {}},
            "filter_results": {"israel_jobs": 0, "non_israel_jobs": 0, "raw_count": 0, "deduped_count": 0, "locations": {}},
            "run_history": [],
            "jobs_trend": [],
            "top_companies": [],
            "alerts": [{"type": "danger", "message": f"Dashboard error: {str(e)}"}],
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })


@app.route('/api/kpis')
def api_kpis():
    """API endpoint for KPIs only."""
    return jsonify(get_core_kpis())


@app.route('/api/coverage')
def api_coverage():
    """API endpoint for company coverage."""
    return jsonify(get_company_coverage())


@app.route('/api/filter')
def api_filter():
    """API endpoint for filter results."""
    return jsonify(get_filter_results())


@app.route('/api/analytics/overview')
def api_analytics_overview():
    try:
        today = datetime.utcnow().date()
        start = _parse_ymd_date(request.args.get("start"), today - timedelta(days=30))
        end = _parse_ymd_date(request.args.get("end"), today)
        if end < start:
            return jsonify({"error": "Invalid date range: end must be >= start"}), 400

        companies = _split_csv_param(request.args.get("companies", ""))
        keyword = _normalize_text(request.args.get("keyword", ""))
        rows = _get_desc_reqs_rows(start, end, companies=companies or None, keyword=keyword or None)

        return jsonify({
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "filters": {"companies": companies, "keyword": keyword},
            "overview": _analytics_overview(rows),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/top-companies')
def api_analytics_top_companies():
    try:
        today = datetime.utcnow().date()
        start = _parse_ymd_date(request.args.get("start"), today - timedelta(days=30))
        end = _parse_ymd_date(request.args.get("end"), today)
        if end < start:
            return jsonify({"error": "Invalid date range: end must be >= start"}), 400

        companies = _split_csv_param(request.args.get("companies", ""))
        keyword = _normalize_text(request.args.get("keyword", ""))
        limit = min(max(int(request.args.get("limit", 10)), 1), 50)
        rows = _get_desc_reqs_rows(start, end, companies=companies or None, keyword=keyword or None)
        return jsonify({"items": _analytics_top_companies(rows, limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/top-titles')
def api_analytics_top_titles():
    try:
        today = datetime.utcnow().date()
        start = _parse_ymd_date(request.args.get("start"), today - timedelta(days=30))
        end = _parse_ymd_date(request.args.get("end"), today)
        if end < start:
            return jsonify({"error": "Invalid date range: end must be >= start"}), 400

        companies = _split_csv_param(request.args.get("companies", ""))
        keyword = _normalize_text(request.args.get("keyword", ""))
        limit = min(max(int(request.args.get("limit", 10)), 1), 50)
        rows = _get_desc_reqs_rows(start, end, companies=companies or None, keyword=keyword or None)
        return jsonify({"items": _analytics_top_titles(rows, limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/top-requirements')
def api_analytics_top_requirements():
    try:
        today = datetime.utcnow().date()
        start = _parse_ymd_date(request.args.get("start"), today - timedelta(days=30))
        end = _parse_ymd_date(request.args.get("end"), today)
        if end < start:
            return jsonify({"error": "Invalid date range: end must be >= start"}), 400

        companies = _split_csv_param(request.args.get("companies", ""))
        keyword = _normalize_text(request.args.get("keyword", ""))
        limit = min(max(int(request.args.get("limit", 15)), 1), 100)
        rows = _get_desc_reqs_rows(start, end, companies=companies or None, keyword=keyword or None)
        return jsonify({"items": _analytics_top_requirements(rows, limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/trend')
def api_analytics_trend():
    try:
        today = datetime.utcnow().date()
        start = _parse_ymd_date(request.args.get("start"), today - timedelta(days=30))
        end = _parse_ymd_date(request.args.get("end"), today)
        if end < start:
            return jsonify({"error": "Invalid date range: end must be >= start"}), 400

        companies = _split_csv_param(request.args.get("companies", ""))
        keyword = _normalize_text(request.args.get("keyword", ""))
        rows = _get_desc_reqs_rows(start, end, companies=companies or None, keyword=keyword or None)
        return jsonify({"items": _analytics_trend(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/companies')
def api_analytics_companies():
    """Return company options for the analytics filter dropdown."""
    try:
        today = datetime.utcnow().date()
        start = _parse_ymd_date(request.args.get("start"), today - timedelta(days=30))
        end = _parse_ymd_date(request.args.get("end"), today)
        rows = _get_desc_reqs_rows(start, end)
        companies = sorted({_normalize_text(r.get("Company", "")) for r in rows if _normalize_text(r.get("Company", ""))})
        return jsonify({"items": companies})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/matching-jobs')
def api_analytics_matching_jobs():
    """Return matching jobs (desc + reqs) for keyword investigation."""
    try:
        today = datetime.utcnow().date()
        start = _parse_ymd_date(request.args.get("start"), today - timedelta(days=30))
        end = _parse_ymd_date(request.args.get("end"), today)
        if end < start:
            return jsonify({"error": "Invalid date range: end must be >= start"}), 400

        companies = _split_csv_param(request.args.get("companies", ""))
        keyword = _normalize_text(request.args.get("keyword", ""))
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)

        conn = get_supabase_connection()
        if not conn:
            return jsonify({"items": []})

        start_iso = datetime.combine(start, datetime.min.time()).isoformat() + "Z"
        end_iso = datetime.combine(end + timedelta(days=1), datetime.min.time()).isoformat() + "Z"

        query = (
            conn.table("desc_reqs_scrapers")
            .select("Company, JobDesc, desc, reqs, Link, created_at")
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .order("created_at", desc=True)
            .limit(limit * 4)
        )
        if companies:
            query = query.in_("Company", companies)
        rows = query.execute().data or []

        items = []
        kw = keyword.lower()
        for row in rows:
            company = _normalize_text(row.get("Company", ""))
            title = _normalize_text(row.get("JobDesc", ""))
            desc = _normalize_text(row.get("desc", ""))
            reqs_items = _parse_reqs_field(row.get("reqs", ""))
            reqs_text = " ".join(reqs_items)
            haystack = f"{company} {title} {desc} {reqs_text}".lower()

            if kw and kw not in haystack:
                continue

            items.append({
                "company": company,
                "job_title": title,
                "created_at": row.get("created_at"),
                "link": _normalize_text(row.get("Link", "")),
                "desc": desc,
                "reqs": reqs_items,
            })
            if len(items) >= limit:
                break

        return jsonify({"items": items, "count": len(items)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/companies')
def api_companies():
    """API endpoint for top companies."""
    return jsonify(get_top_companies())


@app.route('/api/alerts')
def api_alerts():
    """API endpoint for alerts."""
    return jsonify(get_alerts())


@app.route('/api/run-history')
def api_run_history():
    """API endpoint for run history."""
    return jsonify(get_run_history(limit=15))


@app.route('/api/trend')
def api_trend():
    """API endpoint for trend data."""
    return jsonify(get_jobs_trend(days=7))


@app.route('/api/emailed-jobs')
def api_emailed_jobs():
    """API endpoint for jobs sent via email today."""
    return jsonify(get_emailed_jobs_today())


@app.route('/api/emailed-jobs/filtered')
def api_emailed_jobs_filtered():
    """API endpoint for filtered jobs sent via email today."""
    data = get_emailed_jobs_today()
    return jsonify({
        "date": data["date"],
        "count": data["filtered_count"],
        "jobs": data["filtered_jobs"]
    })


@app.route('/api/emailed-jobs/unfiltered')
def api_emailed_jobs_unfiltered():
    """API endpoint for unfiltered jobs sent via email today."""
    data = get_emailed_jobs_today()
    return jsonify({
        "date": data["date"],
        "count": data["unfiltered_count"],
        "jobs": data["unfiltered_jobs"]
    })


@app.route('/api/emailed-jobs/history')
def api_emailed_jobs_history():
    """API endpoint for email history stats (last 30 days)."""
    return jsonify(get_email_history_stats())


@app.route('/api/emailed-jobs/dates')
def api_emailed_jobs_dates():
    """API endpoint for available email dates."""
    return jsonify({"dates": get_available_email_dates()})


@app.route('/api/emailed-jobs/by-date/<target_date>')
def api_emailed_jobs_by_date(target_date):
    """API endpoint for jobs sent via email on a specific date."""
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    return jsonify(get_emailed_jobs_by_date(target_date))


@app.route('/api/ai-stats')
def api_ai_stats():
    """Return total AI-analyzed job count and junior-suitable rate."""
    try:
        conn = get_supabase_connection()
        if not conn:
            return jsonify({"total_analyzed": 0, "junior_suitable_rate": 0})

        # Count rows in desc_reqs_scrapers using a column that always exists
        resp = conn.table("desc_reqs_scrapers").select("Company").execute()
        total = len(resp.data or [])

        # Derive junior-suitable rate from emailed_jobs_history (is_filtered = junior)
        rate = 0
        try:
            email_resp = conn.table("emailed_jobs_history").select("is_filtered").execute()
            email_rows = email_resp.data or []
            if email_rows:
                junior = sum(1 for r in email_rows if r.get("is_filtered", False))
                rate = round(junior / len(email_rows) * 100)
        except Exception:
            pass

        return jsonify({"total_analyzed": total, "junior_suitable_rate": rate})
    except Exception as e:
        return jsonify({"error": str(e), "total_analyzed": 0, "junior_suitable_rate": 0})


@app.route('/api/jobs/today')
def api_jobs_today():
    """API endpoint for jobs in scrapers_data created today (UTC)."""
    return jsonify({"jobs": get_today_jobs()})


@app.route('/api/jobs/details')
def api_job_details():
    """API endpoint for job description/requirements by link."""
    link = request.args.get("link", "").strip()
    if not link:
        return jsonify({"error": "Missing 'link' query parameter"}), 400

    details = get_job_details_by_link(link)

    status_code = 200
    if not details.get("has_details", False) and "error" in details:
        status_code = 500

    return jsonify(details), status_code


# ============== Admin Endpoints ==============

@app.route('/api/admin/me')
@require_admin
def admin_me():
    """Verify auth status and return the admin email."""
    return jsonify({"email": request.admin_email, "role": "admin"})


@app.route('/api/admin/companies', methods=['GET'])
@require_admin
def admin_list_companies():
    """List all companies (including inactive) for admin management."""
    try:
        conn = get_supabase_connection()
        if not conn:
            return jsonify({"error": "Database unavailable"}), 500
        response = conn.table("company_data").select("*").order("company").execute()
        return jsonify({"companies": response.data or []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/admin/companies', methods=['POST'])
@require_admin
def admin_add_company():
    """Add or update a company in the database."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    company = data.get("company", "").strip()
    link_type = data.get("link_type", "").strip()
    unique_identifier = data.get("unique_identifier", "").strip()

    if not company:
        return jsonify({"error": "Company name is required"}), 400
    if not link_type:
        return jsonify({"error": "Link type is required"}), 400
    if link_type not in VALID_LINK_TYPES:
        return jsonify({"error": f"Invalid link type: {link_type}. Must be one of {VALID_LINK_TYPES}"}), 400

    try:
        conn = get_supabase_connection()
        if not conn:
            return jsonify({"error": "Database unavailable"}), 500

        record = {
            "company": company,
            "link_type": link_type,
            "is_active": True,
            "consecutive_failures": 0,
            "updated_at": datetime.now().isoformat(),
        }
        if unique_identifier:
            record["unique_identifier"] = unique_identifier

        response = conn.table("company_data").upsert(
            record, on_conflict="company,link_type"
        ).execute()

        if response.data:
            return jsonify({"success": True, "company": response.data[0]}), 201
        return jsonify({"success": True}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", os.environ.get("DASHBOARD_PORT", 5050)))
    debug = not IS_RENDER
    app.run(debug=debug, host='0.0.0.0', port=port)
