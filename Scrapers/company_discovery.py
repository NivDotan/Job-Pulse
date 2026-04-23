"""
Company Discovery — orchestrator + CLI
---------------------------------------
Finds new Israeli companies on supported ATS platforms, adds them to
the database, and emails a summary report.

Modules:
  discovery_search.py  — search engine layer (DDG / Brave / Bing / CC)
  discovery_ats.py     — per-ATS discover & validate functions

Usage:
  python company_discovery.py                      # discover all ATS types
  python company_discovery.py --dry-run            # preview, no DB writes
  python company_discovery.py --ats workday        # one ATS only
  python company_discovery.py --validate-known     # test against DB/local fallback
  python company_discovery.py --debug              # verbose search output
"""

import argparse
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from alerting import send_alert_email
from db_operations import get_next_discovery_ats, get_supabase_client, update_discovery_run
from discovery_ats import DISCOVERERS

logger = logging.getLogger(__name__)

# ── DB helpers ──────────────────────────────────────────────────────────────

def get_existing_companies() -> Set[tuple]:
    """Return set of (link_type, company_slug) from DB, lowercased."""
    try:
        resp = get_supabase_client().table("company_data").select("company,link_type").execute()
        return {(row["link_type"], row["company"].lower()) for row in resp.data}
    except Exception as e:
        logger.error(f"Failed to load existing companies: {e}")
        return set()


def add_companies_to_db(companies: List[Dict]) -> List[Dict]:
    """
    Upsert newly discovered companies into company_data.
    Workday instance URL is stored in unique_identifier.
    Returns the successfully inserted records.
    """
    if not companies:
        return []
    client = get_supabase_client()
    inserted = []
    for c in companies:
        try:
            data = {"company": c["Company"], "link_type": c["LinkType"], "is_active": True}
            if c.get("Workday Instance"):
                data["unique_identifier"] = c["Workday Instance"]
            elif c.get("Unique Identifier"):
                data["unique_identifier"] = c["Unique Identifier"]
            client.table("company_data").upsert(data, on_conflict="company,link_type").execute()
            inserted.append(c)
            logger.info(f"DB: added {c['Company']} ({c['LinkType']})")
        except Exception as e:
            logger.error(f"DB insert failed for {c['Company']}: {e}")
    return inserted


# ── Email report ────────────────────────────────────────────────────────────

_BOARD_URL: Dict[str, str] = {
    "green":    "https://boards.greenhouse.io/{slug}",
    "lever":    "https://jobs.lever.co/{slug}",
    "ashby":    "https://jobs.ashbyhq.com/{slug}",
    "bamboohr": "https://{slug}.bamboohr.com/careers",
    "comeet":   "https://www.comeet.com/jobs/{slug}/{identifier}",
    "workday":  "{instance}",
}


def _board_url(c: Dict) -> str:
    tpl = _BOARD_URL.get(c["LinkType"], "")
    if c["LinkType"] == "workday":
        return c.get("Workday Instance", "")
    if c["LinkType"] == "comeet":
        return tpl.format(slug=c["Company"], identifier=c.get("Unique Identifier", ""))
    return tpl.format(slug=c["Company"])


def send_discovery_email(found_by_ats: Dict[str, List[Dict]], dry_run: bool = False) -> bool:
    """Send an HTML summary email of all validated companies (new + existing)."""
    total = sum(len(v) for v in found_by_ats.values())
    total_new = sum(1 for v in found_by_ats.values() for c in v if not c.get("already_in_db"))
    if total == 0:
        logger.info("Nothing found — skipping email")
        return False

    sections = ""
    for ats, companies in found_by_ats.items():
        if not companies:
            continue
        new_count = sum(1 for c in companies if not c.get("already_in_db"))
        rows = "".join(
            "<tr>"
            f"<td>{c['Company']}</td>"
            f"<td><a href='{_board_url(c)}'>{_board_url(c)}</a></td>"
            f"<td style='color:{'#888' if c.get('already_in_db') else '#2e7d32'};font-weight:bold'>"
            f"{'already in DB' if c.get('already_in_db') else '✓ NEW'}</td>"
            "</tr>"
            for c in companies
        )
        sections += f"""
        <h3 style="margin-bottom:4px">{ats.upper()} — {len(companies)} found ({new_count} new)</h3>
        <table border="1" cellpadding="6" cellspacing="0"
               style="border-collapse:collapse;margin-bottom:16px;width:100%">
          <tr style="background:#f2f2f2"><th>Slug</th><th>Board URL</th><th>Status</th></tr>
          {rows}
        </table>
        """

    if dry_run:
        footer = "Dry run — no changes made to the database."
    elif total_new:
        footer = f"<strong>{total_new} new</strong> companies added to the database and will be scraped on the next run."
    else:
        footer = "All discovered companies are already in the database."

    body = f"""
    <h2>Company Discovery Report{' (DRY RUN)' if dry_run else ''}</h2>
    <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
    <p><strong>Validated:</strong> {total} &nbsp;|&nbsp;
       <strong>New:</strong> {total_new} &nbsp;|&nbsp;
       <strong>Already in DB:</strong> {total - total_new}</p>
    {sections}
    <p style="margin-top:16px">{footer}</p>
    """

    return send_alert_email(
        subject=f"Discovery: {total} found, {total_new} new — {datetime.now().strftime('%Y-%m-%d')}",
        body=body,
        alert_type="discovery",
    )


# ── Orchestrator ────────────────────────────────────────────────────────────

def run_discovery(
    ats_filter: Optional[str] = None,
    dry_run: bool = False,
    debug: bool = False,
    validate_known: bool = False,
) -> Dict[str, List[Dict]]:
    """
    Discover new companies on supported ATS platforms.

    Args:
        ats_filter:     If set, only run for this ATS (e.g. "workday").
        dry_run:        Validate and report but do not insert into DB.
        debug:          Print expanded queries and every search URL found.
        validate_known: Use local/DB fallback candidates when search is blocked.

    Returns:
        Dict mapping ATS key → list of discovered company dicts.
    """
    existing = get_existing_companies()
    logger.info(f"Loaded {len(existing)} existing (link_type, company) pairs from DB")

    targets = {ats_filter: DISCOVERERS[ats_filter]} if ats_filter else DISCOVERERS

    found_by_ats: Dict[str, List[Dict]] = {}
    for ats_type, discover_fn in targets.items():
        logger.info(f"── Discovering {ats_type} ──")
        try:
            candidates = discover_fn(existing, debug=debug, validate_known=validate_known)
            if not dry_run:
                add_companies_to_db([c for c in candidates if not c.get("already_in_db")])
            found_by_ats[ats_type] = candidates
        except Exception as e:
            logger.error(f"Discovery failed for {ats_type}: {e}")
            found_by_ats[ats_type] = []
        time.sleep(5)

    send_discovery_email(found_by_ats, dry_run=dry_run)

    total = sum(len(v) for v in found_by_ats.values())
    total_new = sum(1 for v in found_by_ats.values() for c in v if not c.get("already_in_db"))
    logger.info(f"Discovery complete — {total} found, {total_new} new")
    return found_by_ats


# ── Scheduled entry point (called from CleanScript) ────────────────────────

def run_discovery_if_due(interval_hours: int = 24) -> None:
    """
    Run discovery for the single most-overdue ATS type, then update state.

    Called at the end of every CleanScript run. With 6 ATS types and a
    24-hour interval each, one ATS is processed per day — no extra Render
    services needed.

    State is tracked in the `discovery_state` Supabase table.
    """
    ats_type = get_next_discovery_ats(interval_hours=interval_hours)
    if not ats_type:
        logger.info("Discovery: all ATS types are up to date, nothing to run")
        return

    logger.info(f"Discovery: running for overdue ATS '{ats_type}'")
    try:
        results = run_discovery(ats_filter=ats_type)
        companies = results.get(ats_type, [])
        found = len(companies)
        new_count = sum(1 for c in companies if not c.get("already_in_db"))
        update_discovery_run(ats_type, found=found, new_count=new_count)
        logger.info(f"Discovery: {ats_type} done — {found} found, {new_count} new")
    except Exception as e:
        logger.error(f"Discovery: failed for {ats_type}: {e}")
        # Still update state so we don't retry the same ATS on every run
        update_discovery_run(ats_type, found=0, new_count=0)


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Discover new Israeli companies on ATS platforms")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and report but do not modify the database")
    parser.add_argument("--ats", choices=list(DISCOVERERS.keys()),
                        help="Limit to a single ATS type")
    parser.add_argument("--debug", action="store_true",
                        help="Print expanded queries and every search URL found")
    parser.add_argument("--validate-known", action="store_true",
                        help="Use local/DB fallback candidates when search returns nothing")
    args = parser.parse_args()

    results = run_discovery(
        ats_filter=args.ats,
        dry_run=args.dry_run,
        debug=args.debug,
        validate_known=args.validate_known,
    )

    print("\n=== DISCOVERY SUMMARY ===")
    total = total_new = 0
    for ats, companies in results.items():
        if companies:
            new_count = sum(1 for c in companies if not c.get("already_in_db"))
            print(f"\n{ats.upper()} ({len(companies)} found, {new_count} new):")
            for c in companies:
                tag = "[already in DB]" if c.get("already_in_db") else "[NEW]"
                extra = f"  ->  {c.get('Workday Instance', '')}" if c.get("Workday Instance") else ""
                print(f"  {tag} {c['Company']}{extra}")
            total += len(companies)
            total_new += new_count

    print(f"\nTotal: {total} found, {total_new} new")
    if args.dry_run:
        print("(DRY RUN — no DB changes)")
