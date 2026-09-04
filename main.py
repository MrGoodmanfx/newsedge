"""
main.py
-------
NewsEdge entry point.

Runs a background loop that:
  1. Periodically refreshes the economic calendar.
  2. Watches upcoming High-impact events and fires Telegram alerts
     at the right moments (1hr before, 30min before, 5min before).
  3. Once an event has released (actual value present) and enters
     the spike-avoidance window, sends the entry-window-open alert.

This is meant to run continuously in the background (e.g. in its
own terminal window) while you use the Streamlit dashboard
separately for the visual interface. Run with: python main.py
"""

import time
from datetime import datetime, timedelta
import pytz

from config import CALENDAR_REFRESH_MINUTES
from data.database import init_db, get_upcoming_events, has_alert_been_sent, mark_alert_sent
from data.calendar import refresh_calendar
from utils.timezone import utc_to_eat, eat_now
from alerts.telegram import (
    send_preparation_alert,
    send_checklist_alert,
    send_final_warning,
    send_entry_window_alert,
)
from alerts.checklist import generate_pre_event_checklist, checklist_to_text

LOOP_INTERVAL_SECONDS = 30  # How often the main loop checks for due alerts (only used by run_main_loop)


def check_and_send_alerts():
    """
    Check all upcoming High-impact events and send any alerts that
    are due (1hr/30min/5min before, or entry-window-open after release).

    Uses the sent_alerts database table (not in-memory state) to avoid
    duplicates - this makes it safe to call from a one-shot script
    (e.g. a GitHub Actions cron run) as well as from the continuous
    run_main_loop() below. Each alert type has a WIDE window (rather
    than a tight ~60s band) so infrequent check cadences (e.g. every
    5 minutes via cron) don't miss the window between two runs -
    "already sent" tracking prevents re-sending once it fires.

    Note: with a 5-minute check cadence, the 5-min-before warning and
    entry-window alerts may fire slightly later than their ideal
    moment in the worst case. The 1hr and 30min prep alerts are
    unaffected since their windows are wide relative to the drift.
    """
    events = get_upcoming_events(limit=200)
    now_utc = datetime.now(pytz.utc)

    for event in events:
        if event["impact_level"] != "High":
            continue

        event_dt_utc = datetime.fromisoformat(event["event_datetime_utc"])
        if event_dt_utc.tzinfo is None:
            event_dt_utc = pytz.utc.localize(event_dt_utc)

        seconds_until = (event_dt_utc - now_utc).total_seconds()
        event_key_base = event["event_datetime_utc"]

        # 1 hour before - fires any time between 45-60 min out
        if 2700 <= seconds_until <= 3600:
            key = f"{event['event_name']}|{event_key_base}|1hr"
            if not has_alert_been_sent(key):
                send_preparation_alert(event["event_name"], minutes_until=60)
                mark_alert_sent(key)

        # 30 minutes before - fires any time between 15-30 min out
        if 900 <= seconds_until <= 1800:
            key = f"{event['event_name']}|{event_key_base}|30min"
            if not has_alert_been_sent(key):
                first_asset = (event["affected_assets"] or "EURUSD").split(",")[0]
                forecast = event["forecast_value"] if event["forecast_value"] is not None else 1.0
                checklist = generate_pre_event_checklist(event["event_name"], first_asset, forecast)
                send_checklist_alert(checklist_to_text(checklist))
                mark_alert_sent(key)

        # 5 minutes before - fires any time between 0-10 min out (still pre-event)
        if 0 <= seconds_until <= 600:
            key = f"{event['event_name']}|{event_key_base}|5min"
            if not has_alert_been_sent(key):
                send_final_warning(event["event_name"])
                mark_alert_sent(key)

        # Entry window open - once the event has fired (actual known)
        # and we're within ~10 minutes after release, send the "safe
        # to enter" alert (fires once, regardless of exact 60-90s timing).
        if event["actual_value"] is not None and -600 <= seconds_until <= 0:
            key = f"{event['event_name']}|{event_key_base}|entry_window"
            if not has_alert_been_sent(key):
                first_asset = (event["affected_assets"] or "EURUSD").split(",")[0]
                send_entry_window_alert(first_asset)
                mark_alert_sent(key)


def run_main_loop():
    """
    Main background loop: refreshes the calendar periodically and
    checks for due alerts every LOOP_INTERVAL_SECONDS. Runs forever
    until interrupted (Ctrl+C).
    """
    print("NewsEdge starting up...")
    init_db()

    last_calendar_refresh = None

    print(f"Current time (EAT): {eat_now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Entering main loop. Press Ctrl+C to stop.\n")

    while True:
        now = datetime.now(pytz.utc)

        # Refresh calendar on startup and then every CALENDAR_REFRESH_MINUTES
        if (last_calendar_refresh is None or
                (now - last_calendar_refresh) >= timedelta(minutes=CALENDAR_REFRESH_MINUTES)):
            try:
                count = refresh_calendar()
                print(f"[{eat_now().strftime('%H:%M:%S')}] Calendar refreshed - {count} events.")
                last_calendar_refresh = now
            except Exception as e:
                print(f"[{eat_now().strftime('%H:%M:%S')}] Calendar refresh failed: {e}")

        try:
            check_and_send_alerts()
        except Exception as e:
            print(f"[{eat_now().strftime('%H:%M:%S')}] Alert check failed: {e}")

        time.sleep(LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        run_main_loop()
    except KeyboardInterrupt:
        print("\nNewsEdge stopped.")