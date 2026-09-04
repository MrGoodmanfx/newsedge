"""
engine/spike_detector.py
-------------------------
Detects the initial spike/manipulation wick that occurs in the first
60 seconds after a high-impact news release, and tells the trader
when it's actually safe to enter (after the fake-out has resolved
and price has begun its real retrace/continuation).

This directly implements feature #5 from the spec: most retail
traders lose money by entering during the initial spike, which is
often a stop-hunt/liquidity grab before the real move. This module
gives a clear "wait" / "entry window open" signal.
"""

from datetime import datetime, timedelta
import pytz

from config import SPIKE_AVOID_SECONDS, ENTRY_WINDOW_SECONDS
from data.prices import get_price_window


def get_spike_status(event_datetime_utc: datetime, now_utc: datetime = None) -> dict:
    """
    Determine what phase of the post-news timeline we're currently in,
    relative to a news event's release time.

    Args:
        event_datetime_utc: The event's release time, in UTC.
        now_utc: Current time in UTC. Defaults to actual current time
                 if not provided (mainly overridable for testing).

    Returns:
        A dict: {
            "phase": "pre_event" / "spike_zone" / "entry_window" / "post_window",
            "seconds_since_event": float,
            "seconds_until_safe_entry": float or 0,
            "message": human-readable status string,
        }
    """
    if now_utc is None:
        now_utc = datetime.now(pytz.utc)

    if event_datetime_utc.tzinfo is None:
        event_datetime_utc = pytz.utc.localize(event_datetime_utc)
    if now_utc.tzinfo is None:
        now_utc = pytz.utc.localize(now_utc)

    seconds_since_event = (now_utc - event_datetime_utc).total_seconds()

    if seconds_since_event < 0:
        return {
            "phase": "pre_event",
            "seconds_since_event": seconds_since_event,
            "seconds_until_safe_entry": None,
            "message": "Event has not released yet.",
        }

    if seconds_since_event < SPIKE_AVOID_SECONDS:
        remaining = SPIKE_AVOID_SECONDS - seconds_since_event
        return {
            "phase": "spike_zone",
            "seconds_since_event": seconds_since_event,
            "seconds_until_safe_entry": remaining,
            "message": f"DO NOT ENTER - spike/manipulation window. "
                       f"Wait {int(remaining)} more seconds.",
        }

    if seconds_since_event < ENTRY_WINDOW_SECONDS:
        remaining = ENTRY_WINDOW_SECONDS - seconds_since_event
        return {
            "phase": "entry_window",
            "seconds_since_event": seconds_since_event,
            "seconds_until_safe_entry": 0,
            "message": f"ENTRY WINDOW OPEN - safe to enter now. "
                       f"({int(remaining)}s left in optimal window)",
        }

    return {
        "phase": "post_window",
        "seconds_since_event": seconds_since_event,
        "seconds_until_safe_entry": 0,
        "message": "Optimal entry window has passed - re-check retrace "
                   "levels before entering, price may have already moved.",
    }


def detect_spike_and_retrace(asset: str, event_datetime_utc: datetime) -> dict:
    """
    Using 1-minute price data, detect the initial spike direction/size
    in the first 60 seconds after an event, and identify the retrace
    zone (where smart money typically enters after the fake-out).

    Note: yfinance's finest granularity is 1-minute bars, so this
    treats the first 1-minute candle after the event as the "spike"
    candle. This is a reasonable approximation but won't capture
    sub-minute wicks. For tick-level precision you'd need a broker
    feed or tick data provider - flagging this as a known limitation.

    Args:
        asset: One of the keys in config.ASSETS.
        event_datetime_utc: The event's release time, in UTC.

    Returns:
        A dict: {
            "spike_detected": bool,
            "spike_direction": "up" / "down" / None,
            "spike_open": float or None,
            "spike_high": float or None,
            "spike_low": float or None,
            "spike_close": float or None,
            "retrace_zone_low": float or None,
            "retrace_zone_high": float or None,
            "note": explanation string,
        }
    """
    window_start = event_datetime_utc - timedelta(minutes=1)
    window_end = event_datetime_utc + timedelta(minutes=3)

    data = get_price_window(asset, window_start, window_end, interval="1m")

    if data.empty:
        return {
            "spike_detected": False,
            "spike_direction": None,
            "spike_open": None, "spike_high": None,
            "spike_low": None, "spike_close": None,
            "retrace_zone_low": None, "retrace_zone_high": None,
            "note": "No 1-minute price data available for this window "
                    "(event may be too old, or outside market hours).",
        }

    if data.index.tz is not None:
        data.index = data.index.tz_convert("UTC").tz_localize(None)

    event_naive = event_datetime_utc.astimezone(pytz.utc).replace(tzinfo=None) \
        if event_datetime_utc.tzinfo else event_datetime_utc

    # Find the candle closest to the event time - this is our "spike candle".
    time_diffs = abs(data.index - event_naive)
    spike_idx = time_diffs.argmin()
    spike_candle = data.iloc[spike_idx]

    spike_open = float(spike_candle["Open"])
    spike_high = float(spike_candle["High"])
    spike_low = float(spike_candle["Low"])
    spike_close = float(spike_candle["Close"])

    spike_direction = "up" if spike_close > spike_open else "down"

    # Retrace zone: the middle 50% of the spike candle's range - this
    # is the typical "fair value" zone price returns to after the
    # initial stop-hunt wick, before the real directional move resumes.
    candle_range = spike_high - spike_low
    if spike_direction == "up":
        retrace_zone_high = spike_high - (candle_range * 0.25)
        retrace_zone_low = spike_high - (candle_range * 0.50)
    else:
        retrace_zone_high = spike_low + (candle_range * 0.50)
        retrace_zone_low = spike_low + (candle_range * 0.25)

    return {
        "spike_detected": True,
        "spike_direction": spike_direction,
        "spike_open": spike_open,
        "spike_high": spike_high,
        "spike_low": spike_low,
        "spike_close": spike_close,
        "retrace_zone_low": round(retrace_zone_low, 5),
        "retrace_zone_high": round(retrace_zone_high, 5),
        "note": "Retrace zone estimated from the 25-50% pullback area of "
                "the initial spike candle's range.",
    }