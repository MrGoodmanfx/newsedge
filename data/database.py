"""
data/database.py
-----------------
SQLite database layer for NewsEdge.
Handles creating tables and reading/writing:
  - economic calendar events
  - historical price reactions to past events
  - post-event trade logs (your personal journal)

All other modules that need persistence go through this file
rather than touching SQLite directly - keeps the schema in one place.
"""

import sqlite3
import os
from contextlib import contextmanager
from typing import Optional

from config import DATABASE_PATH


def _ensure_data_dir():
    """Make sure the folder holding the database file exists."""
    data_dir = os.path.dirname(DATABASE_PATH)
    os.makedirs(data_dir, exist_ok=True)


@contextmanager
def get_connection():
    """
    Context manager that yields a SQLite connection and guarantees
    it is closed afterward, even if an error occurs.

    Usage:
        with get_connection() as conn:
            conn.execute(...)
    """
    _ensure_data_dir()
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # Lets us access columns by name
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """
    Create all required tables if they do not already exist.
    Safe to call every time the app starts - it will not wipe data.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Economic calendar events (this week's and past events)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                event_tier TEXT,
                event_datetime_utc TEXT NOT NULL,
                impact_level TEXT,
                previous_value REAL,
                forecast_value REAL,
                actual_value REAL,
                affected_assets TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_name, event_datetime_utc)
            )
        """)

        # Historical price reactions - one row per (event, asset) pair
        # after an event has occurred, storing how price moved.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                asset TEXT NOT NULL,
                deviation_score REAL,
                deviation_class TEXT,
                move_15min REAL,
                move_1hr REAL,
                move_4hr REAL,
                direction_correct INTEGER,
                event_datetime_utc TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Post-event personal trade journal
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                asset TEXT NOT NULL,
                event_datetime_utc TEXT NOT NULL,
                deviation_score REAL,
                direction_taken TEXT,
                entry_price REAL,
                exit_price REAL,
                pnl_pips REAL,
                outcome TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_datetime ON calendar_events(event_datetime_utc)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reactions_event ON historical_reactions(event_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tradelog_event ON trade_log(event_name)")

        # Tracks which alerts have already been sent, so a scheduled/cron
        # process (which restarts fresh each run, e.g. GitHub Actions)
        # doesn't send duplicate Telegram alerts for the same event.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sent_alerts (
                alert_key TEXT PRIMARY KEY,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def has_alert_been_sent(alert_key: str) -> bool:
    """
    Check whether an alert with this key has already been sent.

    Args:
        alert_key: A unique string identifying the alert, e.g.
                    "NFP|2026-09-04T15:30:00|1hr"

    Returns:
        True if already sent, False otherwise.
    """
    with get_connection() as conn:
        cursor = conn.execute("SELECT 1 FROM sent_alerts WHERE alert_key = ?", (alert_key,))
        return cursor.fetchone() is not None


def mark_alert_sent(alert_key: str):
    """
    Record that an alert has been sent, so it won't be sent again.

    Args:
        alert_key: A unique string identifying the alert.
    """
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_alerts (alert_key) VALUES (?)",
            (alert_key,)
        )


def upsert_calendar_event(event: dict):
    """
    Insert a new calendar event, or update it if it already exists
    (matched on event_name + event_datetime_utc).

    Args:
        event: dict with keys matching the calendar_events columns.
               Required: event_name, event_datetime_utc
               Optional: event_tier, impact_level, previous_value,
                         forecast_value, actual_value, affected_assets
    """
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO calendar_events
                (event_name, event_tier, event_datetime_utc, impact_level,
                 previous_value, forecast_value, actual_value, affected_assets)
            VALUES (:event_name, :event_tier, :event_datetime_utc, :impact_level,
                    :previous_value, :forecast_value, :actual_value, :affected_assets)
            ON CONFLICT(event_name, event_datetime_utc) DO UPDATE SET
                impact_level=excluded.impact_level,
                previous_value=excluded.previous_value,
                forecast_value=excluded.forecast_value,
                actual_value=excluded.actual_value,
                affected_assets=excluded.affected_assets
        """, {
            "event_name": event.get("event_name"),
            "event_tier": event.get("event_tier"),
            "event_datetime_utc": event.get("event_datetime_utc"),
            "impact_level": event.get("impact_level"),
            "previous_value": event.get("previous_value"),
            "forecast_value": event.get("forecast_value"),
            "actual_value": event.get("actual_value"),
            "affected_assets": event.get("affected_assets"),
        })


def get_upcoming_events(limit: int = 50):
    """
    Fetch calendar events, most recent/upcoming first.

    Args:
        limit: max number of rows to return.

    Returns:
        A list of sqlite3.Row objects (dict-like access).
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT * FROM calendar_events
            ORDER BY event_datetime_utc ASC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()


def log_historical_reaction(reaction: dict):
    """
    Save a historical price reaction record for an (event, asset) pair.

    Args:
        reaction: dict with keys: event_name, asset, deviation_score,
                  deviation_class, move_15min, move_1hr, move_4hr,
                  direction_correct (0 or 1), event_datetime_utc
    """
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO historical_reactions
                (event_name, asset, deviation_score, deviation_class,
                 move_15min, move_1hr, move_4hr, direction_correct, event_datetime_utc)
            VALUES (:event_name, :asset, :deviation_score, :deviation_class,
                    :move_15min, :move_1hr, :move_4hr, :direction_correct, :event_datetime_utc)
        """, reaction)


def get_historical_reactions(event_name: str):
    """
    Get all historical reactions logged for a given event type.
    Used by engine/historical.py to compute averages.

    Args:
        event_name: e.g. "NFP", "CPI"

    Returns:
        A list of sqlite3.Row objects.
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT * FROM historical_reactions
            WHERE event_name = ?
            ORDER BY event_datetime_utc DESC
        """, (event_name,))
        return cursor.fetchall()


def log_trade(trade: dict):
    """
    Save a post-event trade to your personal journal.

    Args:
        trade: dict with keys: event_name, asset, event_datetime_utc,
               deviation_score, direction_taken, entry_price, exit_price,
               pnl_pips, outcome, notes
    """
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO trade_log
                (event_name, asset, event_datetime_utc, deviation_score,
                 direction_taken, entry_price, exit_price, pnl_pips, outcome, notes)
            VALUES (:event_name, :asset, :event_datetime_utc, :deviation_score,
                    :direction_taken, :entry_price, :exit_price, :pnl_pips, :outcome, :notes)
        """, trade)


def get_trade_log(event_name: Optional[str] = None):
    """
    Retrieve trade journal entries, optionally filtered by event name.

    Args:
        event_name: if provided, only return trades for this event type.

    Returns:
        A list of sqlite3.Row objects.
    """
    with get_connection() as conn:
        if event_name:
            cursor = conn.execute(
                "SELECT * FROM trade_log WHERE event_name = ? ORDER BY created_at DESC",
                (event_name,)
            )
        else:
            cursor = conn.execute("SELECT * FROM trade_log ORDER BY created_at DESC")
        return cursor.fetchall()