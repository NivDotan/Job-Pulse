"""
Analytics helpers for the dashboard.

Provides aggregation and NLP-style analysis over job records fetched from
desc_reqs_scrapers: requirement token extraction, top-companies/titles/requirements
summaries, and date-bucketed trend data.
"""
import os
import re
import json
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from supabase_client import get_supabase_connection
from standardization import (
    canonicalize_link,
    clean_text,
    extract_skill_terms,
    normalize_ats,
    normalize_status,
    normalize_timestamp,
    parse_requirements,
    standardize_company,
    standardize_job_record,
    standardize_location,
    standardize_title,
)


ANALYTICS_STOPWORDS = {
    "and", "the", "for", "with", "you", "your", "our", "are", "will", "from", "that",
    "this", "have", "has", "job", "work", "team", "years", "year", "experience",
    "required", "preferred", "ability", "skills", "skill", "using", "must", "plus",
    "knowledge", "strong", "good", "etc"
}

TECHNICAL_TAXONOMY_CATEGORIES = {
    "programming_languages": "Programming languages",
    "cloud_infrastructure": "Cloud & infrastructure",
    "data_analytics": "Data & analytics",
    "ai_ml": "AI / ML",
    "frontend_backend": "Application engineering",
    "security": "Security",
}


def _parse_ymd_date(raw, default_date):
    if not raw:
        return default_date
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        return default_date


def _split_csv_param(raw):
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x and x.strip()]


def _normalize_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalize_title(value):
    title = _normalize_text(value).lower()
    title = re.sub(r"[\(\)\[\]\|_/\\-]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def _parse_reqs_field(reqs):
    if reqs is None:
        return []
    if isinstance(reqs, list):
        return [_normalize_text(x) for x in reqs if _normalize_text(x)]

    text = _normalize_text(reqs)
    if not text:
        return []

    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [_normalize_text(x) for x in parsed if _normalize_text(x)]
        except Exception:
            pass

    parts = re.split(r"\n|;|•|- ", text)
    return [_normalize_text(p) for p in parts if _normalize_text(p)]


def _extract_requirement_tokens(req_items):
    counts = Counter()
    for item in req_items:
        lowered = item.lower()
        cleaned = re.sub(r"[^a-z0-9\+\#\.\- ]+", " ", lowered)
        words = [w for w in cleaned.split() if len(w) >= 3 and w not in ANALYTICS_STOPWORDS]
        for w in words:
            counts[w] += 1
    return counts


def _get_desc_reqs_rows(start_date, end_date, companies=None, keyword=None):
    conn = get_supabase_connection()
    if not conn:
        return []

    start_iso = datetime.combine(start_date, datetime.min.time()).isoformat() + "Z"
    end_iso = datetime.combine(end_date + timedelta(days=1), datetime.min.time()).isoformat() + "Z"

    all_rows = []
    page_size = 1000
    max_rows = int(os.environ.get("ANALYTICS_MAX_ROWS", "5000"))
    offset = 0

    while offset < max_rows:
        query = (
            conn.table("desc_reqs_scrapers")
            .select("Company, JobDesc, reqs, created_at")
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .order("created_at", desc=False)
            .range(offset, offset + page_size - 1)
        )
        if companies:
            query = query.in_("Company", companies)
        resp = query.execute()
        page = resp.data or []
        if not page:
            break
        all_rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    if keyword:
        kw = keyword.lower()
        filtered = []
        for row in all_rows:
            title = _normalize_text(row.get("JobDesc", ""))
            reqs_text = _normalize_text(row.get("reqs", ""))
            company = _normalize_text(row.get("Company", ""))
            if kw in f"{company} {title} {reqs_text}".lower():
                filtered.append(row)
        all_rows = filtered

    return all_rows


def _analytics_overview(rows):
    companies = set()
    titles = set()
    rows_with_reqs = 0
    req_items_total = 0

    for row in rows:
        company = _normalize_text(row.get("Company", ""))
        title = _normalize_title(row.get("JobDesc", ""))
        req_items = _parse_reqs_field(row.get("reqs", ""))
        if company:
            companies.add(company)
        if title:
            titles.add(title)
        if req_items:
            rows_with_reqs += 1
            req_items_total += len(req_items)

    avg_reqs = round(req_items_total / len(rows), 2) if rows else 0
    return {
        "total_records": len(rows),
        "unique_companies": len(companies),
        "unique_titles": len(titles),
        "rows_with_requirements": rows_with_reqs,
        "avg_requirements_per_record": avg_reqs,
    }


def _analytics_top_companies(rows, limit):
    counter = Counter()
    for row in rows:
        company = _normalize_text(row.get("Company", ""))
        if company:
            counter[company] += 1
    return [{"company": k, "count": v} for k, v in counter.most_common(limit)]


def _analytics_top_titles(rows, limit):
    counter = Counter()
    for row in rows:
        title = _normalize_title(row.get("JobDesc", ""))
        if title:
            counter[title] += 1
    return [{"title": k, "count": v} for k, v in counter.most_common(limit)]


def _analytics_top_requirements(rows, limit):
    counter = Counter()
    for row in rows:
        req_items = _parse_reqs_field(row.get("reqs", ""))
        counter.update(_extract_requirement_tokens(req_items))
    return [{"term": k, "count": v} for k, v in counter.most_common(limit)]


def _analytics_trend(rows):
    by_day = defaultdict(int)
    for row in rows:
        created_at = row.get("created_at")
        if not created_at:
            continue
        day = str(created_at)[:10]
        by_day[day] += 1
    return [{"date": d, "count": by_day[d]} for d in sorted(by_day.keys())]


def _safe_execute(query):
    try:
        return query.execute().data or []
    except Exception as e:
        print(f"Portfolio analytics query failed: {e}")
        return []


def _fetch_table_rows(conn, table_name, select_expr, start=None, end=None, date_col="created_at", limit=5000):
    query = conn.table(table_name).select(select_expr)
    if start and date_col:
        start_iso = start.isoformat() if date_col == "email_date" else datetime.combine(start, datetime.min.time()).isoformat() + "Z"
        query = query.gte(date_col, start_iso)
    if end and date_col:
        end_iso = (end + timedelta(days=1)).isoformat() if date_col == "email_date" else datetime.combine(end + timedelta(days=1), datetime.min.time()).isoformat() + "Z"
        query = query.lt(date_col, end_iso)
    if date_col:
        query = query.order(date_col, desc=True)
    return _safe_execute(query.limit(limit))


def _fetch_enriched_rows(conn, start, end, limit):
    """Fetch LLM-enriched rows from the current desc_reqs_scrapers schema."""
    base_select = "Company, JobDesc, Link, desc, reqs, created_at"
    query = conn.table("desc_reqs_scrapers").select(base_select)
    if start:
        query = query.gte("created_at", datetime.combine(start, datetime.min.time()).isoformat() + "Z")
    if end:
        query = query.lt("created_at", datetime.combine(end + timedelta(days=1), datetime.min.time()).isoformat() + "Z")
    return _safe_execute(query.order("created_at", desc=True).limit(limit))


def _matches_portfolio_filters(job, companies=None, keyword=None, country=None, seniority=None):
    companies = companies or []
    if companies:
        wanted = {standardize_company(c)["normalized"] for c in companies}
        if job["company"]["normalized"] not in wanted:
            return False

    if country and country.lower() != "all":
        if job["location"]["country"].lower() != country.lower():
            return False

    if seniority and seniority.lower() != "all":
        if job["title"]["seniority"].lower() != seniority.lower():
            return False

    if keyword:
        haystack = " ".join([
            job["company"]["display"],
            job["title"]["display"],
            job["location"]["display"],
            job["description"]["text"],
            " ".join(job["requirements"]),
        ]).lower()
        if keyword.lower() not in haystack:
            return False

    return True


def _dedupe_jobs_by_link(jobs):
    deduped = []
    seen = set()
    for job in jobs:
        key = job["link"]["canonical"] or f"{job['company']['normalized']}::{job['title']['normalized']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    return deduped


def _empty_portfolio(start, end, filters):
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "filters": filters,
        "summary": {
            "live_jobs": 0,
            "analyzed_jobs": 0,
            "junior_suitable_jobs": 0,
            "emailed_jobs": 0,
            "companies_monitored": 0,
            "active_companies": 0,
            "unique_hiring_companies": 0,
            "countries": 0,
            "latest_run_at": "",
            "latest_run_status": "Unknown",
            "freshness_hours": None,
        },
        "funnel": [
            {"stage": "Scraped", "count": 0},
            {"stage": "Standardized", "count": 0},
            {"stage": "LLM Enriched", "count": 0},
            {"stage": "Junior Suitable", "count": 0},
            {"stage": "Emailed", "count": 0},
        ],
        "trends": [],
        "skills": [],
        "skill_taxonomy": {},
        "listing_analysis": {
            "requirement_blueprint": [],
            "seniority_matrix": [],
            "seniority_shifts": [],
        },
        "job_types": [],
        "experience_levels": [],
        "education": [],
        "locations": {"countries": [], "cities": [], "workplace": []},
        "companies": {"top_hiring": [], "health": []},
        "quality": {
            "score": 0,
            "missing_descriptions": 0,
            "missing_requirements": 0,
            "duplicate_links": 0,
            "unknown_locations": 0,
            "unknown_junior_labels": 0,
            "invalid_links": 0,
        },
        "matching_jobs": [],
        "methodology": [
            "Scrape supported ATS platforms and normalize jobs into a common schema.",
            "Standardize messy text at read time so analytics do not mutate source rows.",
            "Enrich job descriptions and requirements with LLM extraction when available.",
            "Classify junior suitability, deduplicate by canonical URL, and track delivery history.",
        ],
    }


def _seniority_bucket(job):
    experience_level = job.get("experience", {}).get("level", "Unspecified")
    if experience_level in {"Entry", "Mid", "Senior"}:
        return experience_level
    title_level = job.get("title", {}).get("seniority", "Unspecified")
    if title_level in {"Intern", "Entry"}:
        return "Entry"
    if title_level in {"Senior", "Manager"}:
        return "Senior"
    return "Unspecified"


def _top_terms(counter, limit=5):
    return [{"term": term, "count": count} for term, count in counter.most_common(limit)]


def _listing_analysis(enriched_jobs):
    total_jobs = max(1, len(enriched_jobs))
    category_job_counter = {category: Counter() for category in TECHNICAL_TAXONOMY_CATEGORIES}
    category_mention_counter = {category: Counter() for category in TECHNICAL_TAXONOMY_CATEGORIES}
    seniority = defaultdict(lambda: {
        "jobs": 0,
        "min_years": [],
        "skills": Counter(),
        "cloud": Counter(),
        "data": Counter(),
        "ai_ml": Counter(),
        "education": Counter(),
        "job_types": Counter(),
    })

    for job in enriched_jobs:
        taxonomy = job.get("skill_taxonomy", {})
        bucket = _seniority_bucket(job)
        seniority[bucket]["jobs"] += 1
        min_years = job.get("experience", {}).get("min_years")
        if min_years is not None:
            seniority[bucket]["min_years"].append(min_years)
        seniority[bucket]["education"].update(job.get("education", []))
        seniority[bucket]["job_types"][job.get("job_type", "Other")] += 1

        for category in TECHNICAL_TAXONOMY_CATEGORIES:
            category_counts = taxonomy.get(category, {})
            if not category_counts:
                continue
            category_mention_counter[category].update(category_counts)
            for term in category_counts:
                category_job_counter[category][term] += 1

        combined_skills = Counter()
        for category, counts in taxonomy.items():
            if category in TECHNICAL_TAXONOMY_CATEGORIES:
                combined_skills.update(counts)
        seniority[bucket]["skills"].update(combined_skills)
        seniority[bucket]["cloud"].update(taxonomy.get("cloud_infrastructure", {}))
        seniority[bucket]["data"].update(taxonomy.get("data_analytics", {}))
        seniority[bucket]["ai_ml"].update(taxonomy.get("ai_ml", {}))

    blueprint = []
    for category, label in TECHNICAL_TAXONOMY_CATEGORIES.items():
        top = _top_terms(category_job_counter[category], 6)
        if not top:
            continue
        listing_count = sum(1 for job in enriched_jobs if job.get("skill_taxonomy", {}).get(category))
        blueprint.append({
            "category": label,
            "listing_count": listing_count,
            "coverage_pct": round((listing_count / total_jobs) * 100, 1),
            "top_terms": top,
            "top_mentions": _top_terms(category_mention_counter[category], 6),
        })
    blueprint.sort(key=lambda item: item["listing_count"], reverse=True)

    matrix = []
    for bucket in ["Entry", "Mid", "Senior", "Unspecified"]:
        data = seniority.get(bucket)
        if not data or not data["jobs"]:
            continue
        years = data["min_years"]
        matrix.append({
            "seniority": bucket,
            "jobs": data["jobs"],
            "avg_min_years": round(sum(years) / len(years), 1) if years else None,
            "top_skills": _top_terms(data["skills"], 5),
            "top_cloud": _top_terms(data["cloud"], 3),
            "top_data": _top_terms(data["data"], 3),
            "top_ai_ml": _top_terms(data["ai_ml"], 3),
            "top_education": _top_terms(data["education"], 3),
            "top_job_types": _top_terms(data["job_types"], 3),
        })

    shifts = []
    baseline = seniority.get("Entry", {})
    senior = seniority.get("Senior", {})
    if baseline and senior and baseline.get("jobs") and senior.get("jobs"):
        entry_jobs = baseline["jobs"]
        senior_jobs = senior["jobs"]
        all_terms = set(baseline["skills"]) | set(senior["skills"])
        lift_rows = []
        for term in all_terms:
            entry_rate = baseline["skills"][term] / max(1, entry_jobs)
            senior_rate = senior["skills"][term] / max(1, senior_jobs)
            lift = senior_rate - entry_rate
            if lift > 0:
                lift_rows.append((term, lift, senior["skills"][term], baseline["skills"][term]))
        lift_rows.sort(key=lambda row: row[1], reverse=True)
        shifts = [
            {
                "term": term,
                "senior_lift_pct": round(lift * 100, 1),
                "senior_count": senior_count,
                "entry_count": entry_count,
            }
            for term, lift, senior_count, entry_count in lift_rows[:8]
        ]

    return {
        "requirement_blueprint": blueprint,
        "seniority_matrix": matrix,
        "seniority_shifts": shifts,
    }


def get_portfolio_analytics(start, end, companies=None, keyword="", country="", seniority="", limit=50):
    filters = {
        "companies": companies or [],
        "keyword": clean_text(keyword),
        "country": clean_text(country),
        "seniority": clean_text(seniority),
        "limit": limit,
    }
    empty = _empty_portfolio(start, end, filters)
    conn = get_supabase_connection()
    if not conn:
        return empty

    max_rows = int(os.environ.get("PORTFOLIO_ANALYTICS_MAX_ROWS", "2000"))
    live_rows = _fetch_table_rows(
        conn,
        "scrapers_data",
        "company, job_name, city, link, created_at",
        start=start,
        end=end,
        date_col="created_at",
        limit=max_rows,
    )
    enriched_rows = _fetch_enriched_rows(conn, start=start, end=end, limit=max_rows)
    emailed_rows = _fetch_table_rows(
        conn,
        "emailed_jobs_history",
        "title, company, city, link, sent_at, is_filtered, email_date",
        start=start,
        end=end,
        date_col="email_date",
        limit=max_rows,
    )
    company_rows = _safe_execute(
        conn.table("company_data")
        .select("company, link_type, is_active, consecutive_failures, last_success, last_failure, total_jobs_scraped")
        .limit(max_rows)
    )
    run_rows = _safe_execute(
        conn.table("scraper_log_runs")
        .select("start_time, end_time, duration_seconds, companies_processed, jobs_found, jobs_filtered, error_count, status")
        .order("start_time", desc=True)
        .limit(30)
    )

    live_by_link = {}
    for row in live_rows:
        link_key = canonicalize_link(row.get("link")).get("canonical")
        if link_key and link_key not in live_by_link:
            live_by_link[link_key] = row

    enriched_for_standardization = []
    for row in enriched_rows:
        merged = dict(row)
        live_match = live_by_link.get(canonicalize_link(row.get("Link")).get("canonical"))
        if live_match:
            merged.setdefault("city", live_match.get("city"))
            merged.setdefault("company", live_match.get("company"))
            merged.setdefault("job_name", live_match.get("job_name"))
        enriched_for_standardization.append(merged)

    live_jobs = [standardize_job_record(row, "scrapers_data") for row in live_rows]
    enriched_jobs = [standardize_job_record(row, "desc_reqs_scrapers") for row in enriched_for_standardization]
    emailed_jobs = [standardize_job_record(row, "emailed_jobs_history") for row in emailed_rows]

    live_jobs = [j for j in live_jobs if _matches_portfolio_filters(j, companies, keyword, country, seniority)]
    enriched_jobs = [j for j in enriched_jobs if _matches_portfolio_filters(j, companies, keyword, country, seniority)]
    emailed_jobs = [j for j in emailed_jobs if _matches_portfolio_filters(j, companies, keyword, country, seniority)]
    live_jobs = _dedupe_jobs_by_link(live_jobs)
    enriched_jobs = _dedupe_jobs_by_link(enriched_jobs)
    emailed_jobs = _dedupe_jobs_by_link(emailed_jobs)

    link_counts = Counter(j["link"]["canonical"] for j in live_jobs if j["link"]["canonical"])
    duplicate_links = sum(count - 1 for count in link_counts.values() if count > 1)
    standardized_count = sum(1 for j in live_jobs if j["company"]["normalized"] != "unknown" and j["link"]["canonical"])
    enriched_known_junior = sum(1 for j in enriched_jobs if j["junior"]["label"] != "Unknown")
    emailed_junior_count = sum(1 for j in emailed_jobs if j["junior"]["is_junior_suitable"])
    junior_count = (
        sum(1 for j in enriched_jobs if j["junior"]["is_junior_suitable"])
        if enriched_known_junior
        else emailed_junior_count
    )

    technical_skill_counter = Counter()
    taxonomy_counter = defaultdict(Counter)
    job_type_counter = Counter()
    experience_counter = Counter()
    education_counter = Counter()
    for job in enriched_jobs:
        for category, category_counts in job.get("skill_taxonomy", {}).items():
            taxonomy_counter[category].update(category_counts)
            if category != "business_soft_skills":
                technical_skill_counter.update(category_counts)
        job_type_counter[job.get("job_type", "Other")] += 1
        experience_counter[job.get("experience", {}).get("level", "Unspecified")] += 1
        education_counter.update(job.get("education", ["Unspecified"]))

    country_counter = Counter(j["location"]["country"] for j in live_jobs)
    city_counter = Counter(j["location"]["city"] or j["location"]["display"] for j in live_jobs if j["location"]["country"] != "Unknown")
    workplace_counter = Counter(j["location"]["workplace"] for j in live_jobs)
    company_counter = Counter(j["company"]["display"] for j in live_jobs)

    trend_map = defaultdict(lambda: {"date": "", "live_jobs": 0, "enriched_jobs": 0, "junior_jobs": 0, "emailed_jobs": 0})
    for job in live_jobs:
        day = job["created_at"]["date"]
        if day:
            trend_map[day]["date"] = day
            trend_map[day]["live_jobs"] += 1
    for job in enriched_jobs:
        day = job["created_at"]["date"]
        if day:
            trend_map[day]["date"] = day
            trend_map[day]["enriched_jobs"] += 1
            if job["junior"]["is_junior_suitable"]:
                trend_map[day]["junior_jobs"] += 1
    for job in emailed_jobs:
        day = job["created_at"]["date"]
        if day:
            trend_map[day]["date"] = day
            trend_map[day]["emailed_jobs"] += 1

    latest_run = run_rows[0] if run_rows else {}
    latest_run_time = normalize_timestamp(latest_run.get("start_time"))
    freshness_hours = None
    if latest_run_time["iso"]:
        try:
            dt = datetime.fromisoformat(latest_run_time["iso"].replace("Z", "+00:00")).replace(tzinfo=None)
            freshness_hours = round((datetime.utcnow() - dt).total_seconds() / 3600, 1)
        except Exception:
            freshness_hours = None

    active_companies = sum(1 for row in company_rows if row.get("is_active", True))
    health = []
    for row in company_rows:
        company = standardize_company(row.get("company"))
        ats = normalize_ats(row.get("link_type"))
        failures = row.get("consecutive_failures") or 0
        health.append({
            "company": company["display"],
            "ats": ats["display"],
            "active": bool(row.get("is_active", True)),
            "consecutive_failures": failures,
            "total_jobs_scraped": row.get("total_jobs_scraped") or 0,
        })
    health.sort(key=lambda item: (not item["active"], -item["consecutive_failures"], item["company"]))

    missing_desc = sum(1 for j in enriched_jobs if not j["description"]["text"])
    missing_reqs = sum(1 for j in enriched_jobs if not j["requirements"])
    unknown_locations = sum(1 for j in live_jobs if j["location"]["country"] == "Unknown")
    unknown_junior = sum(1 for j in enriched_jobs if j["junior"]["label"] == "Unknown")
    invalid_links = sum(1 for j in live_jobs if not j["link"]["is_valid"])
    quality_denominator = max(1, len(live_jobs) + len(enriched_jobs))
    issues = missing_desc + missing_reqs + duplicate_links + unknown_locations + unknown_junior + invalid_links
    quality_score = max(0, round(100 - (issues / quality_denominator * 100)))

    matching_jobs = []
    for job in enriched_jobs[:limit]:
        matching_jobs.append({
            "company": job["company"]["display"],
            "job_title": job["title"]["display"],
            "title_family": job["title"]["title_family"],
            "seniority": job["title"]["seniority"],
            "country": job["location"]["country"],
            "city": job["location"]["city"],
            "workplace": job["location"]["workplace"],
            "junior_label": job["junior"]["label"],
            "description_preview": job["description"]["preview"],
            "requirements": job["requirements"][:5],
            "skills": [
                {"term": k, "count": v}
                for category, counts in job.get("skill_taxonomy", {}).items()
                if category != "business_soft_skills"
                for k, v in Counter(counts).most_common(6)
            ][:6],
            "job_type": job.get("job_type", "Other"),
            "experience_level": job.get("experience", {}).get("level", "Unspecified"),
            "min_years": job.get("experience", {}).get("min_years"),
            "education": job.get("education", []),
            "link": job["link"]["canonical"] or job["link"]["raw"],
        })

    latest_status = normalize_status(latest_run.get("status")).get("label", "Unknown")
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "filters": filters,
        "summary": {
            "live_jobs": len(live_jobs),
            "analyzed_jobs": len(enriched_jobs),
            "junior_suitable_jobs": junior_count,
            "emailed_jobs": len(emailed_jobs),
            "companies_monitored": len(company_rows),
            "active_companies": active_companies,
            "unique_hiring_companies": len(company_counter),
            "countries": len([c for c in country_counter if c != "Unknown"]),
            "latest_run_at": latest_run_time["iso"],
            "latest_run_status": latest_status,
            "freshness_hours": freshness_hours,
        },
        "funnel": [
            {"stage": "Scraped", "count": len(live_jobs)},
            {"stage": "Standardized", "count": standardized_count},
            {"stage": "LLM Enriched", "count": len(enriched_jobs)},
            {"stage": "Junior Suitable", "count": junior_count},
            {"stage": "Emailed", "count": len(emailed_jobs)},
        ],
        "trends": [trend_map[d] for d in sorted(trend_map.keys())],
        "skills": [{"term": k, "count": v} for k, v in technical_skill_counter.most_common(20)],
        "skill_taxonomy": {
            category: [{"term": k, "count": v} for k, v in counts.most_common(12)]
            for category, counts in taxonomy_counter.items()
            if category != "business_soft_skills"
        },
        "listing_analysis": _listing_analysis(enriched_jobs),
        "job_types": [{"job_type": k, "count": v} for k, v in job_type_counter.most_common(15)],
        "experience_levels": [{"level": k, "count": v} for k, v in experience_counter.most_common()],
        "education": [{"level": k, "count": v} for k, v in education_counter.most_common()],
        "locations": {
            "countries": [{"country": k, "count": v} for k, v in country_counter.most_common()],
            "cities": [{"city": k, "count": v} for k, v in city_counter.most_common(15)],
            "workplace": [{"workplace": k, "count": v} for k, v in workplace_counter.most_common()],
        },
        "companies": {
            "top_hiring": [{"company": k, "count": v} for k, v in company_counter.most_common(15)],
            "health": health[:20],
        },
        "quality": {
            "score": quality_score,
            "missing_descriptions": missing_desc,
            "missing_requirements": missing_reqs,
            "duplicate_links": duplicate_links,
            "unknown_locations": unknown_locations,
            "unknown_junior_labels": unknown_junior,
            "invalid_links": invalid_links,
        },
        "matching_jobs": matching_jobs,
        "methodology": empty["methodology"],
    }
