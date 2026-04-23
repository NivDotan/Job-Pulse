"""
Search engine layer for company discovery.

Provides a single `ddg_search(query)` entry point that tries, in order:
  1. DuckDuckGo (duckduckgo-search library)
  2. Brave Search (HTML scrape)
  3. Bing (HTML scrape)
  4. Local file cache (7-day TTL)
  5. Common Crawl CDX index
"""

import json
import logging
import os
import re
import time
from typing import List

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

# ── Israel location terms used in every ATS query ──────────────────────────

ISRAEL_TERMS = '"Israel" OR "Tel Aviv" OR "Herzliya" OR "Ramat Gan" OR "Haifa" OR "Beer Sheva"'
COMEET_ISRAEL_TERMS = (
    '"Israel" OR "Tel Aviv" OR "Tel Aviv-Yafo" OR "Tel-Aviv" OR '
    '"Herzliya" OR "Ramat Gan" OR "Haifa" OR "Beer Sheva"'
)

# ── Shared HTTP headers ─────────────────────────────────────────────────────

SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Local result cache ──────────────────────────────────────────────────────

_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_CACHE_PATH = os.path.join(_PROJECT_ROOT, "Scrapers", "tmp", "company_discovery_search_cache.json")
_CACHE_TTL = 7 * 24 * 3600  # 7 days


def _load_cache(query: str, max_results: int, debug: bool = False) -> List[str]:
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    entry = cache.get(query)
    if not isinstance(entry, dict):
        return []

    age = time.time() - entry.get("timestamp", 0)
    if age > _CACHE_TTL:
        return []

    urls = [u for u in entry.get("urls", []) if isinstance(u, str) and u.startswith("http")]
    urls = list(dict.fromkeys(urls))[:max_results]
    if urls:
        logger.warning(
            f"Using cached search results for '{query[:60]}...' "
            f"({len(urls)} URLs, {int(age // 3600)}h old)"
        )
        if debug:
            print(f"--- Cache hit: {len(urls)} URLs ---")
            for u in urls:
                print(f"  {u}")
    return urls


def _save_cache(query: str, urls: List[str]) -> None:
    if not urls:
        return
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        try:
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}
        cache[query] = {"timestamp": time.time(), "urls": list(dict.fromkeys(urls))}
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except OSError as e:
        logger.warning(f"Could not write search cache: {e}")


# ── URL filter ──────────────────────────────────────────────────────────────

def is_ats_url(url: str) -> bool:
    return url.startswith("http") and any(
        d in url
        for d in (
            "greenhouse.io", "lever.co", "ashbyhq.com",
            "bamboohr.com", "myworkdayjobs.com", "comeet.com",
        )
    )


# ── Query expansion ─────────────────────────────────────────────────────────

def _expand_queries(query: str) -> List[str]:
    """Split broad quoted OR queries into smaller queries DDG handles reliably."""
    if " OR " not in query or '"' not in query:
        return [query]
    first_quote = query.find('"')
    base = query[:first_quote].strip()
    terms = re.findall(r'"([^"]+)"', query[first_quote:])
    if not base or not terms:
        return [query]
    expanded = [f"{base} Israel Tel Aviv"]
    for t in terms:
        if " " in t or "-" in t:
            expanded.append(f'{base} "{t}"')
        expanded.append(f"{base} {t}")
    return list(dict.fromkeys(expanded))


# ── Backend: DuckDuckGo ─────────────────────────────────────────────────────

def _ddg(queries: List[str], max_results: int, debug: bool) -> List[str]:
    urls: List[str] = []
    rate_limited = False
    with DDGS(timeout=15) as ddgs:
        for q in queries:
            if rate_limited:
                break
            try:
                results = ddgs.text(q, region="us-en", safesearch="off",
                                    backend="lite", max_results=max_results)
                for r in (results or []):
                    href = r.get("href") or r.get("url")
                    if debug:
                        print(f"  DDG [{q[:40]}] {href!r}  {r.get('title','')[:60]!r}")
                    if href and href.startswith("http"):
                        urls.append(href)
                urls = list(dict.fromkeys(urls))
                if len(urls) >= max_results:
                    break
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"DDG failed '{q[:60]}': {e}")
                if "Ratelimit" in str(e) or " 202 " in str(e):
                    rate_limited = True
                    break
    return urls


# ── Backend: Brave ─────────────────────────────────────────────────────────

def _brave(queries: List[str], max_results: int, debug: bool) -> List[str]:
    urls: List[str] = []
    for q in queries[:2]:
        try:
            resp = requests.get(
                "https://search.brave.com/search",
                params={"q": q, "source": "web"},
                headers=SEARCH_HEADERS, timeout=20,
            )
            if resp.status_code == 429:
                logger.warning("Brave rate-limited")
                break
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if is_ats_url(a["href"]):
                    urls.append(a["href"])
            urls = list(dict.fromkeys(urls))
            if debug:
                print(f"  Brave [{q[:40]}] -> {len(urls)} total URLs")
            if len(urls) >= max_results:
                break
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Brave failed '{q[:60]}': {e}")
    return list(dict.fromkeys(urls))[:max_results]


# ── Backend: Bing ───────────────────────────────────────────────────────────

def _bing(queries: List[str], max_results: int, debug: bool) -> List[str]:
    urls: List[str] = []
    for q in queries[:3]:
        try:
            resp = requests.get(
                "https://www.bing.com/search",
                params={"q": q},
                headers=SEARCH_HEADERS, timeout=20,
            )
            if resp.status_code in {429, 403}:
                logger.warning("Bing rate-limited")
                break
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("li.b_algo h2 a[href], a[href]"):
                href = a.get("href", "")
                if is_ats_url(href):
                    urls.append(href)
            urls = list(dict.fromkeys(urls))
            if debug:
                print(f"  Bing [{q[:40]}] -> {len(urls)} total URLs")
            if len(urls) >= max_results:
                break
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Bing failed '{q[:60]}': {e}")
    return list(dict.fromkeys(urls))[:max_results]


# ── Backend: Common Crawl ───────────────────────────────────────────────────

_CC_FALLBACK_INDEXES = ["CC-MAIN-2026-18", "CC-MAIN-2026-13", "CC-MAIN-2025-51"]
_CC_LOCATION_FRAGMENTS = ["Israel", "Tel-Aviv", "tel-aviv", "Herzliya", "Haifa", "Beer-Sheva"]
_CC_TIMEOUT = 10
_CC_BUDGET = 45


def _cc_patterns(query: str) -> List[str]:
    if "myworkdayjobs.com" in query:
        hosts = ["*.myworkdayjobs.com"]
    elif "greenhouse.io" in query:
        hosts = ["boards.greenhouse.io", "job-boards.greenhouse.io",
                 "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"]
    elif "lever.co" in query:
        hosts = ["jobs.lever.co", "jobs.eu.lever.co"]
    elif "ashbyhq.com" in query:
        hosts = ["jobs.ashbyhq.com"]
    elif "bamboohr.com" in query:
        hosts = ["*.bamboohr.com"]
    elif "comeet.com" in query:
        hosts = ["www.comeet.com/jobs"]
    else:
        return []
    return list(dict.fromkeys(
        f"{h}/*{frag}*" for h in hosts for frag in _CC_LOCATION_FRAGMENTS
    ))


def _cc_index_id(debug: bool) -> str:
    try:
        resp = requests.get(
            "https://index.commoncrawl.org/collinfo.json",
            headers=SEARCH_HEADERS, timeout=20,
        )
        if resp.status_code == 200:
            ids = [item["id"] for item in resp.json() if item.get("id")]
            if ids:
                return ids[0]
    except Exception as e:
        logger.warning(f"Common Crawl index list failed: {e}")
    if debug:
        print("--- Common Crawl using fallback index ---")
    return _CC_FALLBACK_INDEXES[0]


def _commoncrawl(query: str, max_results: int, debug: bool) -> List[str]:
    patterns = _cc_patterns(query)
    if not patterns:
        return []
    urls: List[str] = []
    started = time.time()
    index_id = _cc_index_id(debug)
    for pattern in patterns:
        if time.time() - started > _CC_BUDGET:
            logger.warning("Common Crawl timed out")
            break
        try:
            if debug:
                print(f"  CC [{index_id}] '{pattern}'")
            resp = requests.get(
                f"https://index.commoncrawl.org/{index_id}-index",
                params={"url": pattern, "output": "json", "fl": "url",
                        "collapse": "urlkey", "limit": min(max_results, 20)},
                headers=SEARCH_HEADERS, timeout=_CC_TIMEOUT,
            )
            if resp.status_code not in {200}:
                continue
            for line in resp.text.splitlines():
                try:
                    u = json.loads(line).get("url")
                    if u and u.startswith("http"):
                        urls.append(u)
                except json.JSONDecodeError:
                    pass
            urls = list(dict.fromkeys(urls))
            if len(urls) >= max_results:
                break
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Common Crawl failed for {pattern}: {e}")
    return urls[:max_results]


# ── Public entry point ──────────────────────────────────────────────────────

def ddg_search(query: str, max_results: int = 40, debug: bool = False) -> List[str]:
    """
    Return deduplicated result URLs for a search query.

    Tries DDG → Brave → Bing → cache → Common Crawl in order,
    stopping at the first backend that returns results.
    """
    queries = _expand_queries(query)
    if debug:
        print(f"\n{'='*60}\nSearch: {query}")
        if len(queries) > 1:
            print("Expanded queries:")
            for eq in queries:
                print(f"  {eq}")

    urls = _ddg(queries, max_results, debug)
    if not urls:
        logger.warning("DDG returned nothing; trying Brave")
        urls = _brave(queries, max_results, debug)
    if not urls:
        logger.warning("Brave returned nothing; trying Bing")
        urls = _bing(queries, max_results, debug)
    if not urls:
        urls = _load_cache(query, max_results, debug)
    if not urls:
        logger.warning("All live searches failed; trying Common Crawl")
        urls = _commoncrawl(query, max_results, debug)

    urls = list(dict.fromkeys(urls))[:max_results]
    if urls:
        _save_cache(query, urls)

    logger.info(f"Search '{query[:60]}...' → {len(urls)} URLs")
    if debug and urls:
        print("--- Final URLs ---")
        for u in urls:
            print(f"  {u}")
    return urls
