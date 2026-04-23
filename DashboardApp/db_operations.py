"""
Database Operations Module
--------------------------
Provides database operations for the job scraper system.
Replaces JSON file reads with database queries and manages log metadata storage.
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple
from os.path import join, dirname
from dotenv import load_dotenv
import supabase

# Load environment variables
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

# Configure logging
logger = logging.getLogger(__name__)


# ============================================
# Database Connection
# ============================================

def get_supabase_client():
    """Get Supabase client connection."""
    supabase_url = os.environ.get("supabaseUrl")
    supabase_key = os.environ.get("supabaseKey")
    
    if not supabase_url or not supabase_key:
        raise ValueError("Supabase credentials not found in environment variables")
    
    return supabase.create_client(supabase_url, supabase_key)


# ============================================
# Company Data Operations
# ============================================

# Failure tracking thresholds
CONSECUTIVE_FAILURE_THRESHOLD = 5  # Auto-flag after this many failures
AUTO_DEACTIVATE_THRESHOLD = 10  # Auto-deactivate after this many failures


def get_all_companies(active_only: bool = True) -> List[Dict[str, Any]]:
    """
    Fetch all companies from the database.
    
    Args:
        active_only: If True, only return active companies
        
    Returns:
        List of company dictionaries with keys: Company, LinkType, Unique Identifier
    """
    try:
        client = get_supabase_client()
        query = client.table("company_data").select("*")
        
        if active_only:
            query = query.eq("is_active", True)
        
        response = query.execute()
        
        # Transform to match expected format (same as JSON file structure)
        companies = []
        for row in response.data:
            company = {
                "Company": row["company"],
                "LinkType": row["link_type"]
            }
            if row.get("unique_identifier"):
                company["Unique Identifier"] = row["unique_identifier"]
            companies.append(company)
        
        logger.info(f"Fetched {len(companies)} companies from database")
        return companies
        
    except Exception as e:
        logger.error(f"Error fetching companies from database: {e}")
        raise


def get_company_by_name(company_name: str) -> Optional[Dict[str, Any]]:
    """Fetch a specific company by name."""
    try:
        client = get_supabase_client()
        response = client.table("company_data").select("*").eq("company", company_name).execute()
        
        if response.data:
            return response.data[0]
        return None
        
    except Exception as e:
        logger.error(f"Error fetching company {company_name}: {e}")
        return None


# ============================================
# Company Failure Tracking Operations
# ============================================

def record_company_success(company_name: str, link_type: str, jobs_found: int = 0) -> bool:
    """
    Record a successful scrape for a company.
    Resets consecutive_failures counter and updates last_success.
    
    Args:
        company_name: Name of the company
        link_type: ATS type (green, lever, comeet, etc.)
        jobs_found: Number of jobs found in this scrape
    
    Returns:
        True if updated successfully
    """
    try:
        client = get_supabase_client()
        
        # Update the company record
        client.table("company_data").update({
            "consecutive_failures": 0,
            "last_success": datetime.now().isoformat(),
            "last_error": None,
            "total_jobs_scraped": jobs_found,  # This will be added to existing or set
            "updated_at": datetime.now().isoformat()
        }).eq("company", company_name).eq("link_type", link_type).execute()
        
        logger.debug(f"Recorded success for {company_name} ({link_type}): {jobs_found} jobs")
        return True
        
    except Exception as e:
        logger.error(f"Error recording success for {company_name}: {e}")
        return False


def record_company_failure(
    company_name: str, 
    link_type: str, 
    error_message: str
) -> Dict[str, Any]:
    """
    Record a failed scrape for a company.
    Increments consecutive_failures counter.
    
    Args:
        company_name: Name of the company
        link_type: ATS type
        error_message: The error that occurred
    
    Returns:
        Dict with failure info including whether threshold was exceeded
    """
    result = {
        "company": company_name,
        "link_type": link_type,
        "consecutive_failures": 1,
        "threshold_exceeded": False,
        "auto_deactivated": False
    }
    
    try:
        client = get_supabase_client()
        
        # Get current failure count
        response = client.table("company_data").select(
            "id, consecutive_failures, is_active"
        ).eq("company", company_name).eq("link_type", link_type).execute()
        
        if not response.data:
            logger.warning(f"Company {company_name} ({link_type}) not found in database")
            return result
        
        company = response.data[0]
        current_failures = (company.get("consecutive_failures") or 0) + 1
        result["consecutive_failures"] = current_failures
        
        # Check if we should auto-deactivate
        should_deactivate = current_failures >= AUTO_DEACTIVATE_THRESHOLD
        result["threshold_exceeded"] = current_failures >= CONSECUTIVE_FAILURE_THRESHOLD
        result["auto_deactivated"] = should_deactivate
        
        # Update the company record
        update_data = {
            "consecutive_failures": current_failures,
            "last_error": error_message[:500] if error_message else None,
            "last_failure": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        if should_deactivate and company.get("is_active"):
            update_data["is_active"] = False
            logger.warning(f"Auto-deactivating {company_name} ({link_type}) after {current_failures} failures")
        
        client.table("company_data").update(update_data).eq("id", company["id"]).execute()
        
        logger.info(f"Recorded failure #{current_failures} for {company_name} ({link_type})")
        return result
        
    except Exception as e:
        logger.error(f"Error recording failure for {company_name}: {e}")
        return result


def get_companies_with_failures(min_failures: int = None) -> List[Dict[str, Any]]:
    """
    Get all companies that have consecutive failures.
    
    Args:
        min_failures: Minimum number of consecutive failures (defaults to threshold)
    
    Returns:
        List of company records with failure info
    """
    min_failures = min_failures or CONSECUTIVE_FAILURE_THRESHOLD
    
    try:
        client = get_supabase_client()
        
        response = client.table("company_data").select(
            "company, link_type, consecutive_failures, last_error, last_success, last_failure, is_active"
        ).gte("consecutive_failures", min_failures).order("consecutive_failures", desc=True).execute()
        
        return response.data or []
        
    except Exception as e:
        logger.error(f"Error fetching companies with failures: {e}")
        return []


def reset_company_failures(company_name: str, link_type: str) -> bool:
    """
    Manually reset failure count for a company.
    
    Args:
        company_name: Name of the company
        link_type: ATS type
    
    Returns:
        True if reset successfully
    """
    try:
        client = get_supabase_client()
        
        client.table("company_data").update({
            "consecutive_failures": 0,
            "last_error": None,
            "is_active": True,
            "updated_at": datetime.now().isoformat()
        }).eq("company", company_name).eq("link_type", link_type).execute()
        
        logger.info(f"Reset failures for {company_name} ({link_type})")
        return True
        
    except Exception as e:
        logger.error(f"Error resetting failures for {company_name}: {e}")
        return False


def get_failure_summary() -> Dict[str, Any]:
    """
    Get summary statistics about company failures.
    
    Returns:
        Dict with failure statistics
    """
    try:
        client = get_supabase_client()
        
        # Get all companies with their failure counts
        response = client.table("company_data").select(
            "consecutive_failures, is_active"
        ).execute()
        
        if not response.data:
            return {"total": 0, "with_failures": 0, "auto_deactivated": 0}
        
        total = len(response.data)
        with_failures = sum(1 for c in response.data if (c.get("consecutive_failures") or 0) > 0)
        threshold_exceeded = sum(1 for c in response.data 
                                 if (c.get("consecutive_failures") or 0) >= CONSECUTIVE_FAILURE_THRESHOLD)
        auto_deactivated = sum(1 for c in response.data 
                               if (c.get("consecutive_failures") or 0) >= AUTO_DEACTIVATE_THRESHOLD 
                               and not c.get("is_active"))
        
        return {
            "total_companies": total,
            "companies_with_failures": with_failures,
            "threshold_exceeded": threshold_exceeded,
            "auto_deactivated": auto_deactivated,
            "failure_threshold": CONSECUTIVE_FAILURE_THRESHOLD,
            "deactivation_threshold": AUTO_DEACTIVATE_THRESHOLD
        }
        
    except Exception as e:
        logger.error(f"Error getting failure summary: {e}")
        return {}


def sync_companies_from_json(json_path: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Sync companies from JSON file to database.
    
    This function:
    1. Loads companies from JSON file
    2. Deduplicates the data (same company + link_type)
    3. Compares with existing DB records
    4. Upserts companies (insert or update on conflict)
    5. Marks removed companies as inactive
    
    Args:
        json_path: Path to the JSON file containing company data
        dry_run: If True, don't make changes, just report what would happen
        
    Returns:
        Summary dict with inserted, updated, deactivated counts and details
    """
    summary = {
        "inserted": [],
        "updated": [],
        "deactivated": [],
        "unchanged": 0,
        "errors": [],
        "skipped_duplicates": 0,
        "dry_run": dry_run
    }
    
    try:
        # Load JSON data
        with open(json_path, 'r', encoding='utf-8') as f:
            json_companies = json.load(f)
        
        logger.info(f"Loaded {len(json_companies)} companies from {json_path}")
        
        # Deduplicate JSON data - keep last occurrence of each (company, link_type)
        deduplicated = {}
        for json_company in json_companies:
            company_name = json_company.get("Company", "").strip()
            link_type = json_company.get("LinkType", "").strip()
            if company_name and link_type:
                key = (company_name, link_type)
                if key in deduplicated:
                    summary["skipped_duplicates"] += 1
                deduplicated[key] = json_company
        
        logger.info(f"After deduplication: {len(deduplicated)} unique companies (skipped {summary['skipped_duplicates']} duplicates)")
        
        # Get existing companies from DB
        client = get_supabase_client()
        response = client.table("company_data").select("*").execute()
        existing_companies = {(row["company"], row["link_type"]): row for row in response.data}
        
        logger.info(f"Found {len(existing_companies)} existing companies in database")
        
        # Track which companies we see in JSON
        seen_keys = set()
        
        for key, json_company in deduplicated.items():
            company_name, link_type = key
            unique_id = json_company.get("Unique Identifier", "").strip() if json_company.get("Unique Identifier") else None
            
            seen_keys.add(key)
            
            try:
                if key in existing_companies:
                    # Check if update needed
                    existing = existing_companies[key]
                    needs_update = False
                    
                    if existing.get("unique_identifier") != unique_id:
                        needs_update = True
                    if not existing.get("is_active"):
                        needs_update = True  # Reactivate if it was deactivated
                    
                    if needs_update:
                        if not dry_run:
                            client.table("company_data").update({
                                "unique_identifier": unique_id,
                                "is_active": True,
                                "updated_at": datetime.now().isoformat()
                            }).eq("id", existing["id"]).execute()
                        
                        summary["updated"].append({
                            "company": company_name,
                            "link_type": link_type,
                            "changes": f"unique_id: {existing.get('unique_identifier')} -> {unique_id}"
                        })
                    else:
                        summary["unchanged"] += 1
                else:
                    # Insert new company using upsert to handle race conditions
                    if not dry_run:
                        client.table("company_data").upsert({
                            "company": company_name,
                            "link_type": link_type,
                            "unique_identifier": unique_id,
                            "is_active": True
                        }, on_conflict="company,link_type").execute()
                    
                    summary["inserted"].append({
                        "company": company_name,
                        "link_type": link_type,
                        "unique_identifier": unique_id
                    })
            except Exception as e:
                # Log error but continue with other companies
                error_msg = f"Error processing {company_name} ({link_type}): {str(e)}"
                logger.warning(error_msg)
                summary["errors"].append(error_msg)
                continue
        
        # Deactivate companies not in JSON
        for key, existing in existing_companies.items():
            if key not in seen_keys and existing.get("is_active"):
                try:
                    if not dry_run:
                        client.table("company_data").update({
                            "is_active": False,
                            "updated_at": datetime.now().isoformat()
                        }).eq("id", existing["id"]).execute()
                    
                    summary["deactivated"].append({
                        "company": existing["company"],
                        "link_type": existing["link_type"]
                    })
                except Exception as e:
                    error_msg = f"Error deactivating {existing['company']}: {str(e)}"
                    logger.warning(error_msg)
                    summary["errors"].append(error_msg)
        
        # Log summary
        logger.info(f"Sync complete: {len(summary['inserted'])} inserted, "
                   f"{len(summary['updated'])} updated, "
                   f"{len(summary['deactivated'])} deactivated, "
                   f"{summary['unchanged']} unchanged, "
                   f"{len(summary['errors'])} errors")
        
        return summary
        
    except Exception as e:
        logger.error(f"Error syncing companies from JSON: {e}")
        summary["errors"].append(str(e))
        return summary


# ============================================
# Log Metadata Operations
# ============================================

def parse_log_file_for_metadata(log_path: str) -> Dict[str, Any]:
    """
    Parse a log file and extract metadata.
    
    Returns:
        Dictionary with all log metrics
    """
    metrics = {
        "log_filename": os.path.basename(log_path),
        "start_time": None,
        "end_time": None,
        "duration_seconds": None,
        "companies_processed": 0,
        "total_companies": 0,
        "jobs_found": 0,
        "jobs_filtered": 0,
        "error_count": 0,
        "warning_count": 0,
        "status": "unknown",
        "ats_breakdown": defaultdict(int),
        "top_locations": defaultdict(int),
        "error_summary": []
    }
    
    if not os.path.exists(log_path):
        return metrics
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        logger.error(f"Error reading log file {log_path}: {e}")
        return metrics
    
    for line in lines:
        # Extract timestamp
        timestamp_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        if timestamp_match:
            try:
                timestamp = datetime.strptime(timestamp_match.group(1), "%Y-%m-%d %H:%M:%S")
                if metrics["start_time"] is None:
                    metrics["start_time"] = timestamp
                metrics["end_time"] = timestamp
            except:
                pass
        
        # Processing company - extract total count
        processing_match = re.search(r'Processing.*\[(\d+)/(\d+)\]', line)
        if processing_match:
            current = int(processing_match.group(1))
            total = int(processing_match.group(2))
            metrics["companies_processed"] = max(metrics["companies_processed"], current)
            metrics["total_companies"] = total
        
        # Extract ATS type from processing line
        ats_match = re.search(r"'LinkType':\s*'(\w+)'", line)
        if ats_match and "Processing {" in line:
            ats_type = ats_match.group(1)
            metrics["ats_breakdown"][ats_type] += 1
        
        # Jobs found for company
        if "job titles:" in line:
            jobs_count = line.count("'title':")
            metrics["jobs_found"] += jobs_count
        
        # Filtered jobs
        if "Filtered jobs found" in line:
            filtered_count = line.count("'title':")
            metrics["jobs_filtered"] += filtered_count
        
        # Extract locations from filtered jobs
        loc_matches = re.findall(r"'location':\s*'([^']+)'", line)
        for loc in loc_matches:
            metrics["top_locations"][loc] += 1
        
        # Errors
        if " ERROR:" in line:
            metrics["error_count"] += 1
            error_msg = line.split(" ERROR:")[-1].strip()[:200]
            if error_msg and "Stacktrace" not in error_msg and "GetHandleVerifier" not in error_msg:
                if len(metrics["error_summary"]) < 20:
                    metrics["error_summary"].append(error_msg)
        
        # Warnings
        if " WARNING:" in line:
            metrics["warning_count"] += 1
    
    # Calculate duration
    if metrics["start_time"] and metrics["end_time"]:
        duration = metrics["end_time"] - metrics["start_time"]
        metrics["duration_seconds"] = int(duration.total_seconds())
    
    # Determine status
    if metrics["error_count"] > 10:
        metrics["status"] = "failed"
    elif metrics["companies_processed"] > 0:
        metrics["status"] = "completed"
    else:
        metrics["status"] = "unknown"
    
    # Convert defaultdicts to regular dicts and limit locations
    metrics["ats_breakdown"] = dict(metrics["ats_breakdown"])
    sorted_locations = sorted(metrics["top_locations"].items(), key=lambda x: x[1], reverse=True)[:15]
    metrics["top_locations"] = dict(sorted_locations)
    
    return metrics


def save_log_metadata(metrics: Dict[str, Any]) -> bool:
    """
    Save log run metadata to database.
    
    Args:
        metrics: Dictionary containing log metrics (from parse_log_file_for_metadata)
        
    Returns:
        True if saved successfully, False otherwise
    """
    try:
        client = get_supabase_client()
        
        # Prepare data for insertion
        data = {
            "log_filename": metrics["log_filename"],
            "start_time": metrics["start_time"].isoformat() if metrics["start_time"] else None,
            "end_time": metrics["end_time"].isoformat() if metrics["end_time"] else None,
            "duration_seconds": metrics["duration_seconds"],
            "companies_processed": metrics["companies_processed"],
            "total_companies": metrics["total_companies"],
            "jobs_found": metrics["jobs_found"],
            "jobs_filtered": metrics["jobs_filtered"],
            "error_count": metrics["error_count"],
            "warning_count": metrics["warning_count"],
            "status": metrics["status"],
            "ats_breakdown": json.dumps(metrics["ats_breakdown"]) if metrics["ats_breakdown"] else None,
            "top_locations": json.dumps(metrics["top_locations"]) if metrics["top_locations"] else None,
            "error_summary": json.dumps(metrics["error_summary"]) if metrics["error_summary"] else None
        }
        
        # Upsert (insert or update if filename exists)
        client.table("scraper_log_runs").upsert(data, on_conflict="log_filename").execute()
        
        logger.info(f"Saved log metadata for {metrics['log_filename']}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving log metadata: {e}")
        return False


def get_recent_log_runs(limit: int = 15) -> List[Dict[str, Any]]:
    """
    Get recent log runs from database.
    
    Args:
        limit: Maximum number of records to return
        
    Returns:
        List of log run records ordered by start_time descending
    """
    try:
        client = get_supabase_client()
        response = client.table("scraper_log_runs").select("*").order("start_time", desc=True).limit(limit).execute()
        
        # Parse JSON fields
        results = []
        for row in response.data:
            if row.get("ats_breakdown") and isinstance(row["ats_breakdown"], str):
                row["ats_breakdown"] = json.loads(row["ats_breakdown"])
            if row.get("top_locations") and isinstance(row["top_locations"], str):
                row["top_locations"] = json.loads(row["top_locations"])
            if row.get("error_summary") and isinstance(row["error_summary"], str):
                row["error_summary"] = json.loads(row["error_summary"])
            results.append(row)
        
        return results
        
    except Exception as e:
        logger.error(f"Error fetching log runs: {e}")
        return []


def get_latest_log_run() -> Optional[Dict[str, Any]]:
    """Get the most recent log run from database."""
    runs = get_recent_log_runs(limit=1)
    return runs[0] if runs else None


def get_log_run_by_filename(filename: str) -> Optional[Dict[str, Any]]:
    """Get a specific log run by filename."""
    try:
        client = get_supabase_client()
        response = client.table("scraper_log_runs").select("*").eq("log_filename", filename).execute()
        
        if response.data:
            row = response.data[0]
            # Parse JSON fields
            if row.get("ats_breakdown") and isinstance(row["ats_breakdown"], str):
                row["ats_breakdown"] = json.loads(row["ats_breakdown"])
            if row.get("top_locations") and isinstance(row["top_locations"], str):
                row["top_locations"] = json.loads(row["top_locations"])
            if row.get("error_summary") and isinstance(row["error_summary"], str):
                row["error_summary"] = json.loads(row["error_summary"])
            return row
        return None
        
    except Exception as e:
        logger.error(f"Error fetching log run by filename: {e}")
        return None


def get_jobs_trend_from_db(days: int = 7) -> List[Dict[str, Any]]:
    """
    Get jobs trend data for the last N days from database.
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of daily aggregates with date, jobs_found, jobs_filtered, runs
    """
    try:
        client = get_supabase_client()
        
        # Calculate cutoff date
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        response = client.table("scraper_log_runs").select(
            "start_time, jobs_found, jobs_filtered"
        ).gte("start_time", cutoff_date).order("start_time", desc=False).execute()
        
        # Aggregate by date
        daily_data = defaultdict(lambda: {"jobs_found": 0, "jobs_filtered": 0, "runs": 0})
        
        for row in response.data:
            if row.get("start_time"):
                date_str = row["start_time"][:10]  # Extract YYYY-MM-DD
                daily_data[date_str]["jobs_found"] += row.get("jobs_found", 0) or 0
                daily_data[date_str]["jobs_filtered"] += row.get("jobs_filtered", 0) or 0
                daily_data[date_str]["runs"] += 1
        
        # Build result for last N days
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
        
    except Exception as e:
        logger.error(f"Error fetching jobs trend: {e}")
        return []


def get_company_coverage_from_db() -> Dict[str, Any]:
    """Get company coverage statistics from database."""
    try:
        client = get_supabase_client()
        
        # Get all active companies
        response = client.table("company_data").select("link_type").eq("is_active", True).execute()
        
        coverage = {
            "total_companies": len(response.data),
            "ats_breakdown": defaultdict(int)
        }
        
        for row in response.data:
            ats_type = row.get("link_type", "unknown")
            coverage["ats_breakdown"][ats_type] += 1
        
        coverage["ats_breakdown"] = dict(coverage["ats_breakdown"])
        
        return coverage
        
    except Exception as e:
        logger.error(f"Error fetching company coverage: {e}")
        return {"total_companies": 0, "ats_breakdown": {}}


# ============================================
# Backfill Functions
# ============================================

def backfill_log_metadata(logs_dir: str, limit: int = 100) -> Dict[str, Any]:
    """
    Backfill log metadata from existing log files.
    
    Args:
        logs_dir: Directory containing log files
        limit: Maximum number of log files to process
        
    Returns:
        Summary of backfill operation
    """
    import glob
    
    summary = {
        "processed": 0,
        "saved": 0,
        "errors": []
    }
    
    # Get log files sorted by modification time (newest first)
    log_pattern = os.path.join(logs_dir, "scraper_*.log")
    log_files = glob.glob(log_pattern)
    log_files.sort(key=os.path.getmtime, reverse=True)
    
    # Limit to most recent N files
    log_files = log_files[:limit]
    
    logger.info(f"Found {len(log_files)} log files to process")
    
    for log_path in log_files:
        try:
            summary["processed"] += 1
            metrics = parse_log_file_for_metadata(log_path)
            
            if save_log_metadata(metrics):
                summary["saved"] += 1
            else:
                summary["errors"].append(f"Failed to save: {os.path.basename(log_path)}")
                
        except Exception as e:
            summary["errors"].append(f"{os.path.basename(log_path)}: {str(e)}")
    
    logger.info(f"Backfill complete: {summary['saved']}/{summary['processed']} saved")
    
    return summary


# ============================================
# CLI Interface
# ============================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Database operations for job scraper")
    parser.add_argument("command", choices=["sync", "backfill-logs", "test-connection"],
                       help="Command to execute")
    parser.add_argument("--json-path", default=None,
                       help="Path to company JSON file (for sync command)")
    parser.add_argument("--logs-dir", default=None,
                       help="Path to logs directory (for backfill-logs command)")
    parser.add_argument("--limit", type=int, default=100,
                       help="Maximum number of logs to backfill")
    parser.add_argument("--dry-run", action="store_true",
                       help="Don't make changes, just show what would happen")
    
    args = parser.parse_args()
    
    # Configure logging for CLI
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    
    if args.command == "test-connection":
        try:
            client = get_supabase_client()
            print("Successfully connected to Supabase!")
            
            # Test company_data table
            response = client.table("company_data").select("id").limit(1).execute()
            print(f"company_data table accessible: {response is not None}")
            
            # Test scraper_log_runs table
            response = client.table("scraper_log_runs").select("id").limit(1).execute()
            print(f"scraper_log_runs table accessible: {response is not None}")
            
        except Exception as e:
            print(f"Connection failed: {e}")
    
    elif args.command == "sync":
        json_path = args.json_path or os.path.join(
            dirname(dirname(__file__)), 
            "airflow_processes", "data", "combined_company_data3.json"
        )
        
        print(f"Syncing companies from: {json_path}")
        summary = sync_companies_from_json(json_path, dry_run=args.dry_run)
        
        print(f"\nSync Summary {'(DRY RUN)' if args.dry_run else ''}:")
        print(f"  Inserted: {len(summary['inserted'])}")
        print(f"  Updated: {len(summary['updated'])}")
        print(f"  Deactivated: {len(summary['deactivated'])}")
        print(f"  Unchanged: {summary['unchanged']}")
        
        if summary['errors']:
            print(f"  Errors: {len(summary['errors'])}")
            for err in summary['errors'][:5]:
                print(f"    - {err}")
    
    elif args.command == "backfill-logs":
        logs_dir = args.logs_dir or os.path.join(dirname(__file__), "logs")
        
        print(f"Backfilling log metadata from: {logs_dir}")
        summary = backfill_log_metadata(logs_dir, limit=args.limit)
        
        print(f"\nBackfill Summary:")
        print(f"  Processed: {summary['processed']}")
        print(f"  Saved: {summary['saved']}")
        
        if summary['errors']:
            print(f"  Errors: {len(summary['errors'])}")
            for err in summary['errors'][:5]:
                print(f"    - {err}")
