"""
data/prices.py
---------------
Fetches price data for NewsEdge's assets using yfinance.

Two main jobs:
  1. Get recent/near-real-time prices (yfinance has ~15min delay
     for most feeds, which is fine for post-news trade planning
     since we already wait 60-90s before entering anyway).
  2. Get historical intraday price data around a specific event
     datetime, so engine/historical.py can measure how price moved
     in the 15min / 1hr / 4hr windows after past events.

Crypto (BTCUSDT) can optionally use ccxt for true real-time data,
since Binance's API has no delay - see get_realtime_price_ccxt().
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz

from config import ASSETS


def get_latest_price(asset_symbol: str) -> float:
    """
    Get the most recent available price for an asset.

    Args:
        asset_symbol: One of the keys in config.ASSETS, e.g. "EURUSD".

    Returns:
        The latest closing price as a float, or None if unavailable.
    """
    if asset_symbol not in ASSETS:
        raise ValueError(f"Unknown asset '{asset_symbol}'. Check config.ASSETS.")

    yf_ticker = ASSETS[asset_symbol]
    ticker = yf.Ticker(yf_ticker)

    # Pull the last 1 day of 1-minute data and take the last close.
    data = ticker.history(period="1d", interval="1m")
    if data.empty:
        return None
    return float(data["Close"].iloc[-1])


def get_price_window(asset_symbol: str, start_utc: datetime, end_utc: datetime,
                      interval: str = "1m") -> pd.DataFrame:
    """
    Get historical price data for an asset within a specific UTC time window.
    Used to measure price reaction around a news event.

    Args:
        asset_symbol: One of the keys in config.ASSETS.
        start_utc: Window start (UTC, timezone-aware or naive).
        end_utc: Window end (UTC, timezone-aware or naive).
        interval: yfinance interval string, e.g. "1m", "5m", "15m".
                  Note: yfinance only keeps 1m data for the last ~7 days.

    Returns:
        A pandas DataFrame with OHLCV data indexed by UTC timestamp.
        Empty DataFrame if no data is available.
    """
    if asset_symbol not in ASSETS:
        raise ValueError(f"Unknown asset '{asset_symbol}'. Check config.ASSETS.")

    yf_ticker = ASSETS[asset_symbol]
    ticker = yf.Ticker(yf_ticker)

    # yfinance wants naive datetimes or ISO strings; ensure UTC and drop tzinfo cleanly.
    if start_utc.tzinfo is not None:
        start_utc = start_utc.astimezone(pytz.utc).replace(tzinfo=None)
    if end_utc.tzinfo is not None:
        end_utc = end_utc.astimezone(pytz.utc).replace(tzinfo=None)

    data = ticker.history(start=start_utc, end=end_utc, interval=interval)
    return data


def get_reaction_prices(asset_symbol: str, event_dt_utc: datetime) -> dict:
    """
    Get the price at event time, and at +15min, +1hr, +4hr after,
    for measuring how the asset reacted to a news event.

    Args:
        asset_symbol: One of the keys in config.ASSETS.
        event_dt_utc: The event's release time in UTC.

    Returns:
        A dict: {
            "price_at_event": float or None,
            "price_15min": float or None,
            "price_1hr": float or None,
            "price_4hr": float or None,
        }
        Any value will be None if data wasn't available for that timestamp
        (e.g. event is too far in the past for 1-minute data, or too
        recent for the 4hr mark to have happened yet).
    """
    window_start = event_dt_utc - timedelta(minutes=5)
    window_end = event_dt_utc + timedelta(hours=4, minutes=10)

    data = get_price_window(asset_symbol, window_start, window_end, interval="1m")

    if data.empty:
        return {"price_at_event": None, "price_15min": None, "price_1hr": None, "price_4hr": None}

    # yfinance index may be tz-aware (UTC) - normalize for comparison.
    if data.index.tz is not None:
        data.index = data.index.tz_convert("UTC").tz_localize(None)

    def _closest_price(target_time: datetime):
        """Find the closing price at the timestamp closest to target_time."""
        if data.empty:
            return None
        time_diffs = abs(data.index - target_time)
        closest_idx = time_diffs.argmin()
        return float(data["Close"].iloc[closest_idx])

    if event_dt_utc.tzinfo is not None:
        event_dt_naive = event_dt_utc.astimezone(pytz.utc).replace(tzinfo=None)
    else:
        event_dt_naive = event_dt_utc

    return {
        "price_at_event": _closest_price(event_dt_naive),
        "price_15min": _closest_price(event_dt_naive + timedelta(minutes=15)),
        "price_1hr": _closest_price(event_dt_naive + timedelta(hours=1)),
        "price_4hr": _closest_price(event_dt_naive + timedelta(hours=4)),
    }


def get_realtime_price_ccxt(symbol: str = "BTC/USDT") -> float:
    """
    Get a true real-time price for a crypto asset via Binance (ccxt),
    which has no delay unlike yfinance.

    Args:
        symbol: ccxt-style symbol, e.g. "BTC/USDT".

    Returns:
        The latest traded price as a float, or None on failure.
    """
    try:
        import ccxt
        exchange = ccxt.binance()
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker["last"])
    except Exception as e:
        print(f"[prices.py] ccxt real-time fetch failed: {e}")
        return None