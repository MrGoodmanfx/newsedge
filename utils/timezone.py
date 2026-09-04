"""
utils/timezone.py
------------------
Handles all timezone conversions for NewsEdge.
Economic calendar sources report times in UTC or the source's
local timezone - we normalize everything to East Africa Time (EAT)
since that is where the trader (you) is based.
"""

from datetime import datetime
import pytz

from config import EAT_TIMEZONE


def utc_to_eat(dt_utc: datetime) -> datetime:
    """
    Convert a UTC datetime to East Africa Time (EAT, UTC+3).

    Args:
        dt_utc: A timezone-aware or naive datetime assumed to be UTC.

    Returns:
        A timezone-aware datetime in the Africa/Nairobi timezone.
    """
    utc_zone = pytz.utc
    eat_zone = pytz.timezone(EAT_TIMEZONE)

    # If the datetime has no timezone info, assume it's UTC.
    if dt_utc.tzinfo is None:
        dt_utc = utc_zone.localize(dt_utc)

    return dt_utc.astimezone(eat_zone)


def eat_now() -> datetime:
    """
    Get the current date and time in East Africa Time.

    Returns:
        A timezone-aware datetime representing "now" in EAT.
    """
    eat_zone = pytz.timezone(EAT_TIMEZONE)
    return datetime.now(eat_zone)


def format_eat(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """
    Format a datetime (assumed already in EAT) into a readable string.

    Args:
        dt: The datetime to format.
        fmt: strftime format string.

    Returns:
        A formatted string, e.g. "2026-09-05 15:30".
    """
    return dt.strftime(fmt)


def time_until(event_dt_eat: datetime) -> dict:
    """
    Calculate the time remaining until a given event (in EAT).

    Args:
        event_dt_eat: The event's datetime, already converted to EAT.

    Returns:
        A dict with keys: days, hours, minutes, seconds, total_seconds,
        and is_past (True if the event has already happened).
    """
    now = eat_now()

    # Make sure both datetimes are timezone-aware for safe subtraction.
    if event_dt_eat.tzinfo is None:
        eat_zone = pytz.timezone(EAT_TIMEZONE)
        event_dt_eat = eat_zone.localize(event_dt_eat)

    delta = event_dt_eat - now
    total_seconds = delta.total_seconds()

    if total_seconds <= 0:
        return {
            "days": 0, "hours": 0, "minutes": 0, "seconds": 0,
            "total_seconds": total_seconds, "is_past": True,
        }

    days = int(total_seconds // 86400)
    hours = int((total_seconds % 86400) // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)

    return {
        "days": days, "hours": hours, "minutes": minutes, "seconds": seconds,
        "total_seconds": total_seconds, "is_past": False,
    }


def is_within_next_hours(event_dt_eat: datetime, hours: int = 24) -> bool:
    """
    Check whether an event falls within the next N hours from now (EAT).

    Args:
        event_dt_eat: The event's datetime, in EAT.
        hours: The lookahead window in hours (default 24).

    Returns:
        True if the event is upcoming and within the window, else False.
    """
    result = time_until(event_dt_eat)
    if result["is_past"]:
        return False
    return result["total_seconds"] <= hours * 3600