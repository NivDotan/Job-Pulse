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


ANALYTICS_STOPWORDS = {
    "and", "the", "for", "with", "you", "your", "our", "are", "will", "from", "that",
    "this", "have", "has", "job", "work", "team", "years", "year", "experience",
    "required", "preferred", "ability", "skills", "skill", "using", "must", "plus",
    "knowledge", "strong", "good", "etc"
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
