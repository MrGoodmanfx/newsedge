"""
data/calendar.py
-----------------
Fetches the economic calendar.

Data source: ForexFactory's public calendar JSON feed. This is a
plain JSON endpoint ForexFactory publishes specifically for external
tools to consume - it does not require scraping HTML or bypassing
bot protection, which makes it far more stable than trying to pull
data from investing.com (whose investpy library breaks frequently
because investing.com actively blocks scrapers).

If you later want a paid/more complete data source (Finnhub,
TradingEconomics, etc.) you only need to change the fetch function
here - the rest of NewsEdge (calendar.py's public functions) will
keep working the same way.
"""

import requests
from datetime import datetime
import pytz

from config import TIER_1_EVENTS, TIER_2_EVENTS, TIER_3_EVENTS, EVENT_ASSET_MAP
from utils.timezone import utc_to_eat, is_within_next_hours
from data.database import upsert_calendar_event, get_upcoming_events

FOREXFACTORY_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def _classify_tier(event_title: str) -> str:
    """
    Determine which tier (1, 2, or 3) an event belongs to based on
    its title, using the lists defined in config.py.

    Args:
        event_title: The raw event name from the calendar feed.

    Returns:
        "Tier1", "Tier2", "Tier3", or "Unclassified".
    """
    title_lower = event_title.lower()

    for name in TIER_1_EVENTS:
        if name.lower() in title_lower:
            return "Tier1"
    for name in TIER_2_EVENTS:
        if name.lower() in title_lower:
            return "Tier2"
    for name in TIER_3_EVENTS:
        if name.lower() in title_lower:
            return "Tier3"
    return "Unclassified"


def _affected_assets(event_title: str) -> str:
    """
    Look up which assets are most affected by this event type,
    using EVENT_ASSET_MAP from config.py. Falls back to a default
    set of majors if the event isn't explicitly mapped.

    Args:
        event_title: The raw event name from the calendar feed.

    Returns:
        Comma-separated string of asset symbols, e.g. "EURUSD,XAUUSD".
    """
    title_lower = event_title.lower()
    for key, assets in EVENT_ASSET_MAP.items():
        if key.lower() in title_lower:
            return ",".join(assets)
    return "EURUSD,XAUUSD"  # sensible default for unmapped events


def _parse_float(value):
    """
    Safely convert a calendar value (which may be '', None, '1.2K',
    '3.4%', etc.) into a float, or None if it can't be parsed.

    Args:
        value: Raw string value from the feed.

    Returns:
        A float, or None if parsing fails.
    """
    if value is None or value == "":
        return None
    try:
        cleaned = str(value).replace("%", "").replace("K", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def fetch_forexfactory_calendar() -> list:
    """
    Download and parse this week's economic calendar from ForexFactory.

    Returns:
        A list of dicts, each shaped for data.database.upsert_calendar_event,
        i.e. with keys: event_name, event_tier, event_datetime_utc,
        impact_level, previous_value, forecast_value, actual_value,
        affected_assets.
    """
    response = requests.get(FOREXFACTORY_FEED_URL, timeout=15)
    response.raise_for_status()
    raw_events = response.json()

    parsed_events = []
    for item in raw_events:
        title = item.get("title", "Unknown Event")

        # ForexFactory gives ISO 8601 datetime strings, typically in UTC.
        date_str = item.get("date")
        if not date_str:
            continue
        try:
            event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if event_dt.tzinfo is None:
                event_dt = pytz.utc.localize(event_dt)
            event_dt_utc = event_dt.astimezone(pytz.utc)
        except ValueError:
            continue  # skip events with unparseable dates

        impact = item.get("impact", "Low")  # ForexFactory uses "High"/"Medium"/"Low"

        parsed_events.append({
            "event_name": title,
            "event_tier": _classify_tier(title),
            "event_datetime_utc": event_dt_utc.isoformat(),
            "impact_level": impact,
            "previous_value": _parse_float(item.get("previous")),
            "forecast_value": _parse_float(item.get("forecast")),
            "actual_value": _parse_float(item.get("actual")),
            "affected_assets": _affected_assets(title),
        })

    return parsed_events


def refresh_calendar():
    """
    Fetch the latest calendar from ForexFactory and save every event
    into the database (inserting new events, updating existing ones
    if the actual/forecast values have changed).

    Returns:
        The number of events processed.
    """
    events = fetch_forexfactory_calendar()
    for event in events:
        upsert_calendar_event(event)
    return len(events)


def get_high_impact_this_week() -> list:
    """
    Get all High impact events currently stored in the database,
    sorted soonest first.

    Returns:
        A list of sqlite3.Row objects with impact_level == "High".
    """
    all_events = get_upcoming_events(limit=200)
    return [e for e in all_events if e["impact_level"] == "High"]


def get_events_next_24h() -> list:
    """
    Get events (any impact level) happening within the next 24 hours,
    with their datetime converted to EAT for display.

    Returns:
        A list of dicts: {event_row, eat_datetime}
    """
    all_events = get_upcoming_events(limit=200)
    upcoming = []
    for event in all_events:
        event_dt_utc = datetime.fromisoformat(event["event_datetime_utc"])
        event_dt_eat = utc_to_eat(event_dt_utc)
        if is_within_next_hours(event_dt_eat, hours=24):
            upcoming.append({"event": event, "eat_datetime": event_dt_eat})
    return upcoming