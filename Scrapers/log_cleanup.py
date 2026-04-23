"""
Log Cleanup and Retention Policy
---------------------------------
Manages log files with configurable retention policies:
- Delete logs older than X days
- Optionally compress old logs
- Keep minimum number of recent logs
- Track cleanup history in database
"""

import os
import glob
import gzip
import shutil
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_RETENTION_DAYS = 30  # Delete logs older than 30 days
DEFAULT_COMPRESS_AFTER_DAYS = 7  # Compress logs older than 7 days
MIN_LOGS_TO_KEEP = 10  # Always keep at least 10 recent logs
LOG_PATTERN = "scraper_*.log"


class LogCleanupPolicy:
    """Configuration for log cleanup behavior."""
    
    def __init__(
        self,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        compress_after_days: int = DEFAULT_COMPRESS_AFTER_DAYS,
        min_logs_to_keep: int = MIN_LOGS_TO_KEEP,
        enable_compression: bool = True,
        dry_run: bool = False
    ):
        self.retention_days = retention_days
        self.compress_after_days = compress_after_days
        self.min_logs_to_keep = min_logs_to_keep
        self.enable_compression = enable_compression
        self.dry_run = dry_run


def get_log_files(logs_dir: str, pattern: str = LOG_PATTERN) -> List[Tuple[str, datetime]]:
    """
    Get all log files with their modification times, sorted newest first.
    
    Args:
        logs_dir: Directory containing log files
        pattern: Glob pattern for log files
    
    Returns:
        List of (file_path, mtime) tuples sorted by mtime descending
    """
    log_files = []
    
    for log_path in glob.glob(os.path.join(logs_dir, pattern)):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(log_path))
            log_files.append((log_path, mtime))
        except OSError as e:
            logger.warning(f"Could not get mtime for {log_path}: {e}")
    
    # Also check for compressed logs
    for log_path in glob.glob(os.path.join(logs_dir, f"{pattern}.gz")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(log_path))
            log_files.append((log_path, mtime))
        except OSError as e:
            logger.warning(f"Could not get mtime for {log_path}: {e}")
    
    # Sort by modification time, newest first
    log_files.sort(key=lambda x: x[1], reverse=True)
    return log_files


def compress_log_file(log_path: str, delete_original: bool = True) -> str:
    """
    Compress a log file using gzip.
    
    Args:
        log_path: Path to the log file
        delete_original: Whether to delete the original file after compression
    
    Returns:
        Path to the compressed file
    """
    compressed_path = f"{log_path}.gz"
    
    try:
        with open(log_path, 'rb') as f_in:
            with gzip.open(compressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        if delete_original:
            os.remove(log_path)
        
        # Preserve the original modification time
        original_mtime = os.path.getmtime(log_path) if os.path.exists(log_path) else None
        if original_mtime:
            os.utime(compressed_path, (original_mtime, original_mtime))
        
        logger.info(f"Compressed: {log_path} -> {compressed_path}")
        return compressed_path
        
    except Exception as e:
        logger.error(f"Failed to compress {log_path}: {e}")
        # Clean up partial compressed file if it exists
        if os.path.exists(compressed_path):
            os.remove(compressed_path)
        raise


def delete_log_file(log_path: str) -> bool:
    """
    Delete a log file.
    
    Args:
        log_path: Path to the log file
    
    Returns:
        True if deleted successfully
    """
    try:
        os.remove(log_path)
        logger.info(f"Deleted: {log_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete {log_path}: {e}")
        return False


def cleanup_logs(
    logs_dir: str,
    policy: LogCleanupPolicy = None
) -> Dict[str, Any]:
    """
    Clean up log files according to the retention policy.
    
    Args:
        logs_dir: Directory containing log files
        policy: Cleanup policy configuration
    
    Returns:
        Summary of cleanup actions taken
    """
    if policy is None:
        policy = LogCleanupPolicy()
    
    summary = {
        "total_files": 0,
        "compressed": [],
        "deleted": [],
        "kept": [],
        "errors": [],
        "space_freed_bytes": 0,
        "dry_run": policy.dry_run
    }
    
    if not os.path.exists(logs_dir):
        logger.warning(f"Logs directory does not exist: {logs_dir}")
        return summary
    
    now = datetime.now()
    retention_cutoff = now - timedelta(days=policy.retention_days)
    compress_cutoff = now - timedelta(days=policy.compress_after_days)
    
    log_files = get_log_files(logs_dir)
    summary["total_files"] = len(log_files)
    
    logger.info(f"Found {len(log_files)} log files in {logs_dir}")
    logger.info(f"Retention cutoff: {retention_cutoff}")
    logger.info(f"Compression cutoff: {compress_cutoff}")
    
    # Keep track of how many logs we're keeping
    logs_kept = 0
    
    for log_path, mtime in log_files:
        file_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        is_compressed = log_path.endswith('.gz')
        
        # Always keep minimum number of logs
        if logs_kept < policy.min_logs_to_keep:
            summary["kept"].append(log_path)
            logs_kept += 1
            continue
        
        # Delete if older than retention period
        if mtime < retention_cutoff:
            if policy.dry_run:
                logger.info(f"[DRY RUN] Would delete: {log_path}")
                summary["deleted"].append(log_path)
            else:
                if delete_log_file(log_path):
                    summary["deleted"].append(log_path)
                    summary["space_freed_bytes"] += file_size
                else:
                    summary["errors"].append(f"Failed to delete: {log_path}")
            continue
        
        # Compress if older than compression cutoff and not already compressed
        if policy.enable_compression and mtime < compress_cutoff and not is_compressed:
            if policy.dry_run:
                logger.info(f"[DRY RUN] Would compress: {log_path}")
                summary["compressed"].append(log_path)
            else:
                try:
                    compressed_path = compress_log_file(log_path)
                    summary["compressed"].append(log_path)
                    # Estimate space saved (typically 80-90% compression)
                    compressed_size = os.path.getsize(compressed_path)
                    summary["space_freed_bytes"] += file_size - compressed_size
                except Exception as e:
                    summary["errors"].append(f"Failed to compress {log_path}: {e}")
            continue
        
        # Keep the file as-is
        summary["kept"].append(log_path)
        logs_kept += 1
    
    # Log summary
    logger.info(f"Cleanup summary:")
    logger.info(f"  - Deleted: {len(summary['deleted'])} files")
    logger.info(f"  - Compressed: {len(summary['compressed'])} files")
    logger.info(f"  - Kept: {len(summary['kept'])} files")
    logger.info(f"  - Errors: {len(summary['errors'])}")
    logger.info(f"  - Space freed: {summary['space_freed_bytes'] / 1024 / 1024:.2f} MB")
    
    return summary


def get_logs_disk_usage(logs_dir: str) -> Dict[str, Any]:
    """
    Get disk usage statistics for log files.
    
    Args:
        logs_dir: Directory containing log files
    
    Returns:
        Dict with disk usage statistics
    """
    stats = {
        "total_files": 0,
        "total_size_bytes": 0,
        "compressed_files": 0,
        "compressed_size_bytes": 0,
        "uncompressed_files": 0,
        "uncompressed_size_bytes": 0,
        "oldest_log": None,
        "newest_log": None
    }
    
    if not os.path.exists(logs_dir):
        return stats
    
    log_files = get_log_files(logs_dir)
    stats["total_files"] = len(log_files)
    
    for log_path, mtime in log_files:
        try:
            file_size = os.path.getsize(log_path)
            stats["total_size_bytes"] += file_size
            
            if log_path.endswith('.gz'):
                stats["compressed_files"] += 1
                stats["compressed_size_bytes"] += file_size
            else:
                stats["uncompressed_files"] += 1
                stats["uncompressed_size_bytes"] += file_size
        except OSError:
            pass
    
    if log_files:
        stats["newest_log"] = log_files[0][1].isoformat()
        stats["oldest_log"] = log_files[-1][1].isoformat()
    
    return stats


def schedule_cleanup(logs_dir: str, policy: LogCleanupPolicy = None) -> Dict[str, Any]:
    """
    Run scheduled cleanup - intended to be called from main scraper loop.
    Only runs cleanup once per day.
    
    Args:
        logs_dir: Directory containing log files
        policy: Cleanup policy
    
    Returns:
        Cleanup summary or None if skipped
    """
    # Check if we've already run cleanup today
    marker_file = os.path.join(logs_dir, ".last_cleanup")
    
    if os.path.exists(marker_file):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(marker_file))
            if mtime.date() == datetime.now().date():
                logger.debug("Cleanup already ran today, skipping")
                return None
        except OSError:
            pass
    
    # Run cleanup
    logger.info("Running scheduled log cleanup...")
    summary = cleanup_logs(logs_dir, policy)
    
    # Update marker file
    try:
        Path(marker_file).touch()
    except Exception as e:
        logger.warning(f"Could not update cleanup marker: {e}")
    
    return summary


# ============================================
# CLI Interface
# ============================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Log cleanup utility")
    parser.add_argument(
        "logs_dir",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "logs"),
        help="Directory containing log files"
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Delete logs older than this many days (default: {DEFAULT_RETENTION_DAYS})"
    )
    parser.add_argument(
        "--compress-after-days",
        type=int,
        default=DEFAULT_COMPRESS_AFTER_DAYS,
        help=f"Compress logs older than this many days (default: {DEFAULT_COMPRESS_AFTER_DAYS})"
    )
    parser.add_argument(
        "--min-keep",
        type=int,
        default=MIN_LOGS_TO_KEEP,
        help=f"Minimum number of logs to keep (default: {MIN_LOGS_TO_KEEP})"
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Disable compression (only delete old logs)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show disk usage statistics only"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s'
    )
    
    if args.stats:
        # Just show stats
        stats = get_logs_disk_usage(args.logs_dir)
        print("\n=== Log Disk Usage ===")
        print(f"Total files: {stats['total_files']}")
        print(f"Total size: {stats['total_size_bytes'] / 1024 / 1024:.2f} MB")
        print(f"  - Uncompressed: {stats['uncompressed_files']} files "
              f"({stats['uncompressed_size_bytes'] / 1024 / 1024:.2f} MB)")
        print(f"  - Compressed: {stats['compressed_files']} files "
              f"({stats['compressed_size_bytes'] / 1024 / 1024:.2f} MB)")
        print(f"Oldest log: {stats['oldest_log']}")
        print(f"Newest log: {stats['newest_log']}")
    else:
        # Run cleanup
        policy = LogCleanupPolicy(
            retention_days=args.retention_days,
            compress_after_days=args.compress_after_days,
            min_logs_to_keep=args.min_keep,
            enable_compression=not args.no_compress,
            dry_run=args.dry_run
        )
        
        if args.dry_run:
            print("\n=== DRY RUN MODE ===")
        
        summary = cleanup_logs(args.logs_dir, policy)
        
        print("\n=== Cleanup Summary ===")
        print(f"Total files processed: {summary['total_files']}")
        print(f"Deleted: {len(summary['deleted'])} files")
        print(f"Compressed: {len(summary['compressed'])} files")
        print(f"Kept: {len(summary['kept'])} files")
        print(f"Errors: {len(summary['errors'])}")
        print(f"Space freed: {summary['space_freed_bytes'] / 1024 / 1024:.2f} MB")
        
        if summary['errors']:
            print("\nErrors:")
            for err in summary['errors']:
                print(f"  - {err}")
