"""
Per-ATS company discovery functions.

Each `discover_<ats>(existing, debug, validate_known)` function:
  1. Searches for Israeli companies on that ATS platform
  2. Validates each candidate against the live ATS API
  3. Returns a list of dicts with Company, LinkType, already_in_db, and
     any ATS-specific extras (e.g. Workday Instance, Unique Identifier)

`DISCOVERERS` maps ATS key → function, consumed by company_discovery.py.
"""

import json
import logging
import os
import re
import time
from typing import Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup

from discovery_search import (
    COMEET_ISRAEL_TERMS,
    ISRAEL_TERMS,
    SEARCH_HEADERS,
    ddg_search,
)
from db_operations import get_supabase_client

logger = logging.getLogger(__name__)

# ── Slug/URL helpers ────────────────────────────────────────────────────────

_INVALID_SLUGS = {"embed", "js", "css", "api", "www", "app", "help", "support"}
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_LOCAL_FALLBACK_FILES = [
    os.path.join(_PROJECT_ROOT, "deduplicated_links_for_bot_unclean.json"),
    os.path.join(_PROJECT_ROOT, "deduplicated_links_for_bot.json"),
    os.path.join(_PROJECT_ROOT, "Scrapers", "tmp", "tmp.txt"),
]

_GREENHOUSE_RE = re.compile(
    r"(?:job-boards(?:\.eu)?|boards(?:\.eu)?)\.greenhouse\.io/([a-zA-Z0-9_-]+)"
)
_LEVER_RE = re.compile(r"jobs(?:\.eu)?\.lever\.co/([a-zA-Z0-9_-]+)")
_ASHBY_RE = re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)")
_BAMBOOHR_RE = re.compile(r"([a-zA-Z0-9-]+)\.bamboohr\.com")
_COMEET_RE = re.compile(
    r"https?://(?:www\.)?comeet\.com/jobs/([^/\s?#]+)/([A-Za-z0-9]{2}\.[A-Za-z0-9]{3})"
)
_WORKDAY_RE = re.compile(r"https?://([a-zA-Z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com")

_VALIDATE_KNOWN_LIMIT = 40


def _valid_slug(slug: str) -> bool:
    return (
        bool(slug)
        and slug not in _INVALID_SLUGS
        and len(slug) > 1
        and "/" not in slug
        and "?" not in slug
        and " " not in slug
    )


def _local_texts():
    for path in _LOCAL_FALLBACK_FILES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                yield f.read()
        except OSError:
            pass


def _slugs_from_local(name: str, pattern: re.Pattern, debug: bool = False) -> Set[str]:
    slugs: Set[str] = set()
    for text in _local_texts():
        for m in pattern.finditer(text):
            slug = m.group(1).lower()
            if _valid_slug(slug):
                slugs.add(slug)
    if debug and slugs:
        print(f"--- Local {name} fallback: {len(slugs)} slugs ---")
        for s in sorted(slugs):
            print(f"  {s}")
    return slugs


def _slugs_from_db(link_type: str, debug: bool = False) -> Set[str]:
    try:
        resp = (
            get_supabase_client()
            .table("company_data")
            .select("company")
            .eq("link_type", link_type)
            .execute()
        )
        slugs = {
            r["company"].lower()
            for r in (resp.data or [])
            if _valid_slug(str(r.get("company", "")).lower())
        }
    except Exception as e:
        logger.warning(f"DB fallback failed for {link_type}: {e}")
        return set()
    if debug and slugs:
        print(f"--- DB {link_type} fallback: {len(slugs)} slugs ---")
    return slugs


# ── Greenhouse ──────────────────────────────────────────────────────────────

def discover_greenhouse(
    existing: Set[tuple], debug: bool = False, validate_known: bool = False
) -> List[Dict]:
    urls = ddg_search(f"site:boards.greenhouse.io {ISRAEL_TERMS}", debug=debug)
    time.sleep(3)

    candidates: Set[str] = {
        m.group(1).lower()
        for url in urls
        for m in [_GREENHOUSE_RE.search(url)] if m and _valid_slug(m.group(1).lower())
    }
    if not candidates:
        if validate_known:
            candidates.update(_slugs_from_local("Greenhouse", _GREENHOUSE_RE, debug))
        else:
            logger.warning("[Greenhouse] No search results; pass --validate-known to use local fallback")

    results = []
    for slug in candidates:
        try:
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=10
            )
            if r.status_code == 200 and r.json().get("jobs"):
                in_db = ("green", slug) in existing
                results.append({"Company": slug, "LinkType": "green", "already_in_db": in_db})
                logger.info(f"[Greenhouse] {'exists' if in_db else 'NEW'}: {slug}")
        except Exception:
            pass
        time.sleep(1)

    logger.info(f"[Greenhouse] {len(results)} validated ({sum(1 for r in results if not r['already_in_db'])} new)")
    return results


# ── Lever ───────────────────────────────────────────────────────────────────

def discover_lever(
    existing: Set[tuple], debug: bool = False, validate_known: bool = False
) -> List[Dict]:
    urls = ddg_search(f"site:jobs.lever.co {ISRAEL_TERMS}", debug=debug)
    time.sleep(3)

    candidates: Set[str] = {
        m.group(1).lower()
        for url in urls
        for m in [_LEVER_RE.search(url)] if m and _valid_slug(m.group(1).lower())
    }
    if not candidates:
        if validate_known:
            candidates.update(_slugs_from_local("Lever", _LEVER_RE, debug))
            if not candidates:
                candidates.update(_slugs_from_db("lever", debug))
        else:
            logger.warning("[Lever] No search results; pass --validate-known to use local fallback")

    results = []
    for slug in candidates:
        try:
            jobs = []
            for host in ("api.lever.co", "api.eu.lever.co"):
                r = requests.get(f"https://{host}/v0/postings/{slug}?mode=json", timeout=10)
                if r.status_code == 200 and isinstance(r.json(), list) and r.json():
                    jobs = r.json()
                    break
            if jobs:
                in_db = ("lever", slug) in existing
                results.append({"Company": slug, "LinkType": "lever", "already_in_db": in_db})
                logger.info(f"[Lever] {'exists' if in_db else 'NEW'}: {slug}")
        except Exception:
            pass
        time.sleep(1)

    logger.info(f"[Lever] {len(results)} validated ({sum(1 for r in results if not r['already_in_db'])} new)")
    return results


# ── Ashby ───────────────────────────────────────────────────────────────────

def discover_ashby(
    existing: Set[tuple], debug: bool = False, validate_known: bool = False
) -> List[Dict]:
    urls = ddg_search(f"site:jobs.ashbyhq.com {ISRAEL_TERMS}", debug=debug)
    time.sleep(3)

    candidates: Set[str] = {
        m.group(1).lower()
        for url in urls
        for m in [_ASHBY_RE.search(url)] if m and _valid_slug(m.group(1).lower())
    }
    if not candidates:
        if validate_known:
            candidates.update(_slugs_from_local("Ashby", _ASHBY_RE, debug))
            if not candidates:
                candidates.update(_slugs_from_db("ashby", debug))
        else:
            logger.warning("[Ashby] No search results; pass --validate-known to use local fallback")

    results = []
    for slug in candidates:
        try:
            r = requests.get(
                f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                headers={"Accept": "application/json"}, timeout=10,
            )
            if r.status_code == 200 and r.json().get("jobs"):
                in_db = ("ashby", slug) in existing
                results.append({"Company": slug, "LinkType": "ashby", "already_in_db": in_db})
                logger.info(f"[Ashby] {'exists' if in_db else 'NEW'}: {slug}")
        except Exception:
            pass
        time.sleep(1)

    logger.info(f"[Ashby] {len(results)} validated ({sum(1 for r in results if not r['already_in_db'])} new)")
    return results


# ── BambooHR ────────────────────────────────────────────────────────────────

def discover_bamboohr(
    existing: Set[tuple], debug: bool = False, validate_known: bool = False
) -> List[Dict]:
    urls = ddg_search(f"site:bamboohr.com careers {ISRAEL_TERMS}", debug=debug)
    time.sleep(3)

    candidates: Set[str] = {
        m.group(1).lower()
        for url in urls
        for m in [_BAMBOOHR_RE.search(url)] if m and _valid_slug(m.group(1).lower())
    }
    if not candidates:
        if validate_known:
            candidates.update(_slugs_from_local("BambooHR", _BAMBOOHR_RE, debug))
            if not candidates:
                candidates.update(_slugs_from_db("bamboohr", debug))
        else:
            logger.warning("[BambooHR] No search results; pass --validate-known to use local fallback")

    results = []
    for slug in candidates:
        try:
            r = requests.get(f"https://{slug}.bamboohr.com/careers/list", timeout=10)
            if r.status_code == 200 and r.json().get("result"):
                in_db = ("bamboohr", slug) in existing
                results.append({"Company": slug, "LinkType": "bamboohr", "already_in_db": in_db})
                logger.info(f"[BambooHR] {'exists' if in_db else 'NEW'}: {slug}")
        except Exception:
            pass
        time.sleep(1)

    logger.info(f"[BambooHR] {len(results)} validated ({sum(1 for r in results if not r['already_in_db'])} new)")
    return results


# ── Comeet ──────────────────────────────────────────────────────────────────

def _comeet_from_urls(urls: List[str]) -> Dict[str, Dict]:
    candidates: Dict[str, Dict] = {}
    for url in urls:
        m = _COMEET_RE.search(url)
        if not m:
            continue
        slug = m.group(1).lower()
        identifier = m.group(2)
        if _valid_slug(slug):
            candidates.setdefault(slug, {"company": slug, "url_slug": m.group(1), "unique_identifier": identifier})
    return candidates


def _comeet_from_local(debug: bool = False) -> Dict[str, Dict]:
    candidates: Dict[str, Dict] = {}
    for text in _local_texts():
        for m in _COMEET_RE.finditer(text):
            slug = m.group(1).lower()
            if _valid_slug(slug):
                candidates.setdefault(slug, {"company": slug, "url_slug": m.group(1), "unique_identifier": m.group(2)})
    if debug and candidates:
        print(f"--- Local Comeet fallback: {len(candidates)} candidates ---")
    return candidates


def _comeet_from_db(debug: bool = False) -> Dict[str, Dict]:
    try:
        resp = (
            get_supabase_client()
            .table("company_data")
            .select("company,unique_identifier")
            .eq("link_type", "comeet")
            .execute()
        )
    except Exception as e:
        logger.warning(f"Comeet DB fallback failed: {e}")
        return {}
    candidates: Dict[str, Dict] = {}
    for row in resp.data or []:
        slug = str(row.get("company", "")).lower()
        identifier = str(row.get("unique_identifier", "")).strip()
        if _valid_slug(slug) and identifier:
            candidates[slug] = {"company": slug, "url_slug": slug, "unique_identifier": identifier}
    if debug and candidates:
        print(f"--- DB Comeet fallback: {len(candidates)} candidates ---")
    return candidates


def discover_comeet(
    existing: Set[tuple], debug: bool = False, validate_known: bool = False
) -> List[Dict]:
    urls = ddg_search(f"site:www.comeet.com/jobs/ {COMEET_ISRAEL_TERMS}", debug=debug)
    time.sleep(3)

    candidates = _comeet_from_urls(urls)
    if not candidates:
        if validate_known:
            candidates.update(_comeet_from_local(debug))
            if not candidates:
                candidates.update(_comeet_from_db(debug))
        else:
            logger.warning("[Comeet] No search results; pass --validate-known to use local fallback")

    if validate_known and len(candidates) > _VALIDATE_KNOWN_LIMIT:
        candidates = dict(list(sorted(candidates.items()))[:_VALIDATE_KNOWN_LIMIT])

    results = []
    for slug, candidate in candidates.items():
        identifier = candidate["unique_identifier"]
        url_slug = candidate.get("url_slug", slug)
        board_url = f"https://www.comeet.com/jobs/{url_slug}/{identifier}"
        try:
            r = requests.get(board_url, headers=SEARCH_HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            script = soup.find("script", string=re.compile("COMPANY_POSITIONS_DATA"))
            if not script or not script.string:
                continue
            m = re.search(r"COMPANY_POSITIONS_DATA\s*=\s*(\[.*?\]);", script.string, re.DOTALL)
            if not m:
                continue
            jobs = json.loads(m.group(1).replace("undefined", "null"))
            if isinstance(jobs, list) and jobs:
                in_db = ("comeet", slug) in existing
                results.append({
                    "Company": slug,
                    "LinkType": "comeet",
                    "Unique Identifier": identifier,
                    "already_in_db": in_db,
                })
                logger.info(f"[Comeet] {'exists' if in_db else 'NEW'}: {slug} @ {identifier}")
        except Exception as e:
            if debug:
                logger.warning(f"Comeet validation failed for {slug}: {e}")
        time.sleep(1)

    logger.info(f"[Comeet] {len(results)} validated ({sum(1 for r in results if not r['already_in_db'])} new)")
    return results


# ── Workday ─────────────────────────────────────────────────────────────────

_WORKDAY_ND_VARIANTS = ["wd1", "wd3", "wd5"]


def _workday_from_url(url: str) -> Optional[Dict]:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    m = re.match(r"([a-zA-Z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com", parsed.netloc)
    if not m:
        return None
    slug = m.group(1).lower()
    wdN = m.group(2)
    parts = [p for p in parsed.path.split("/") if p]
    site = None
    if parts:
        site = parts[1] if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]) and len(parts) > 1 else parts[0]
    if not _valid_slug(slug) or not site or site in {"job", "jobs", "apply"}:
        return None
    return {"slug": slug, "base_url": f"https://{slug}.{wdN}.myworkdayjobs.com", "site": site}


def _workday_from_local(debug: bool = False) -> Dict[str, Dict]:
    candidates: Dict[str, Dict] = {}
    for text in _local_texts():
        for m in re.finditer(r"https?://[^\s\"'<>]+myworkdayjobs\.com[^\s\"'<>]*", text):
            parsed = _workday_from_url(m.group(0))
            if parsed:
                candidates.setdefault(parsed["slug"], parsed)
    if debug and candidates:
        print(f"--- Local Workday fallback: {len(candidates)} candidates ---")
    return candidates


def _workday_from_db(debug: bool = False) -> Dict[str, Dict]:
    try:
        resp = (
            get_supabase_client()
            .table("company_data")
            .select("company,unique_identifier")
            .eq("link_type", "workday")
            .execute()
        )
    except Exception as e:
        logger.warning(f"Workday DB fallback failed: {e}")
        return {}
    candidates: Dict[str, Dict] = {}
    for row in resp.data or []:
        slug = str(row.get("company", "")).lower()
        base_url = row.get("unique_identifier")
        if _valid_slug(slug) and base_url:
            parsed = _workday_from_url(base_url)
            candidates[slug] = parsed or {"slug": slug, "base_url": base_url.rstrip("/"), "site": slug}
    if debug and candidates:
        print(f"--- DB Workday fallback: {len(candidates)} candidates ---")
    return candidates


def discover_workday(
    existing: Set[tuple], debug: bool = False, validate_known: bool = False
) -> List[Dict]:
    urls = ddg_search(f"site:myworkdayjobs.com {ISRAEL_TERMS}", debug=debug)
    time.sleep(3)

    candidates: Dict[str, Dict] = {}
    for url in urls:
        parsed = _workday_from_url(url)
        if parsed and parsed["slug"] not in candidates:
            candidates[parsed["slug"]] = parsed

    if not candidates:
        if validate_known:
            candidates.update(_workday_from_local(debug))
            if not candidates:
                candidates.update(_workday_from_db(debug))
        else:
            logger.warning("[Workday] No search results; pass --validate-known to use local fallback")

    results = []
    for slug, candidate in candidates.items():
        try:
            base_url = candidate["base_url"]
            site = candidate["site"]
            r = requests.post(
                f"{base_url}/wday/cxs/{slug}/{site}/jobs",
                json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=15,
            )
            if r.status_code == 200 and r.json().get("jobPostings"):
                in_db = ("workday", slug) in existing
                results.append({
                    "Company": slug,
                    "LinkType": "workday",
                    "Workday Instance": f"{base_url}/{site}",
                    "already_in_db": in_db,
                })
                logger.info(f"[Workday] {'exists' if in_db else 'NEW'}: {slug} @ {base_url}/{site}")
        except Exception:
            pass
        time.sleep(1)

    logger.info(f"[Workday] {len(results)} validated ({sum(1 for r in results if not r['already_in_db'])} new)")
    return results


# ── Registry ────────────────────────────────────────────────────────────────

DISCOVERERS = {
    "green": discover_greenhouse,
    "lever": discover_lever,
    "ashby": discover_ashby,
    "bamboohr": discover_bamboohr,
    "comeet": discover_comeet,
    "workday": discover_workday,
}
