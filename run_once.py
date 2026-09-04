"""
run_once.py
------------
Single-execution entry point for NewsEdge, designed to be triggered
by GitHub Actions on a schedule (e.g. every 5 minutes) instead of
running continuously like main.py's run_main_loop().

Each run: refreshes the calendar, checks for due alerts, sends any
that are due (tracked in the database so no duplicates), then exits.
The database file (data/newsedge.db) must persist between runs for
deduplication to work - the GitHub Actions workflow commits it back
to the repo after each run.
"""

from data.database import init_db
from data.calendar import refresh_calendar
from main import check_and_send_alerts
from utils.timezone import eat_now

if __name__ == "__main__":
    print(f"[{eat_now().strftime('%Y-%m-%d %H:%M:%S')}] NewsEdge run_once starting...")

    init_db()

    try:
        count = refresh_calendar()
        print(f"Calendar refreshed - {count} events.")
    except Exception as e:
        print(f"Calendar refresh failed: {e}")

    try:
        check_and_send_alerts()
        print("Alert check complete.")
    except Exception as e:
        print(f"Alert check failed: {e}")

    print("Done.")