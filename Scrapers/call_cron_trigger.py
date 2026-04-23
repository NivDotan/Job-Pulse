"""
Call the cron-trigger URL and wait for the response.
Use this as the Render Cron Job command so the job calls the web app
and waits for the response (the app then decides whether to run the scraper).

Usage:
  python call_cron_trigger.py              # calls /api/cron-trigger
  python call_cron_trigger.py --test      # calls /api/cron-trigger/test (waits 10 sec on server)

Env:
  CRON_TRIGGER_URL  Base URL (default: https://open-jobs-web-backend.onrender.com)
"""
import os
import sys
import argparse

try:
    import requests
except ImportError:
    print("Error: requests is required. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

DEFAULT_BASE_URL = "https://open-jobs-web-backend.onrender.com"
TIMEOUT = 3600  # 1 hour max wait (scraper can run a long time)


def main():
    parser = argparse.ArgumentParser(description="Call cron-trigger endpoint and wait for response")
    parser.add_argument("--test", action="store_true", help="Hit /api/cron-trigger/test (server sleeps 10 sec)")
    parser.add_argument("--url", default=os.environ.get("CRON_TRIGGER_URL", DEFAULT_BASE_URL), help="Base URL of the app")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    path = "/api/cron-trigger/test" if args.test else "/api/cron-trigger"
    url = base + path

    print(f"Calling {url} (waiting for response)...")
    try:
        r = requests.get(url, timeout=TIMEOUT)
        print(f"Status: {r.status_code}")
        try:
            print(f"Body: {r.json()}")
        except Exception:
            print(f"Body: {r.text[:500]}")
        sys.exit(0 if r.ok else 1)
    except requests.exceptions.Timeout:
        print("Request timed out.", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
