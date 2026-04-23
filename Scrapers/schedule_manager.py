"""
Schedule checking logic for the scraper.

Reads schedule configuration from environment variables and determines
whether the current time falls within the allowed run window.
"""
import os
from datetime import datetime


def is_within_schedule() -> tuple[bool, str]:
    """
    Check if current time is within the allowed schedule.

    Returns:
        Tuple of (is_allowed, reason_message)
    """
    now = datetime.now()

    start_time_str = os.environ.get("SCRAPER_START_HOUR", "08:00")
    end_time_str = os.environ.get("SCRAPER_END_HOUR", "22:30")
    skip_days_str = os.environ.get("SCRAPER_SKIP_DAYS", "5")  # Default: Saturday (5)

    skip_days = [int(d.strip()) for d in skip_days_str.split(",") if d.strip()]

    current_weekday = now.weekday()  # 0=Monday, 6=Sunday
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    if current_weekday in skip_days:
        return False, f"Today is {day_names[current_weekday]} (skip day). Scraper paused."

    try:
        start_hour, start_minute = map(int, start_time_str.split(":"))
        end_hour, end_minute = map(int, end_time_str.split(":"))
    except ValueError:
        start_hour, start_minute = 8, 0
        end_hour, end_minute = 22, 30

    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute

    if current_minutes < start_minutes:
        return False, f"Too early ({now.strftime('%H:%M')}). Schedule starts at {start_time_str}."

    if current_minutes > end_minutes:
        return False, f"Too late ({now.strftime('%H:%M')}). Schedule ended at {end_time_str}."

    return True, f"Within schedule ({start_time_str} - {end_time_str})"
