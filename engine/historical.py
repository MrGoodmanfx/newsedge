"""
engine/historical.py
---------------------
Analyzes historical price reactions stored in the database to answer:
  - On average, how far does price move in 15min / 1hr / 4hr after
    this event type?
  - How often does the initial direction actually hold (accuracy)?
  - Which asset reacts most reliably to this event?
  - What's the worst time to enter (always: first 60 seconds)?

This module is what data/prices.py + engine/deviation.py feed into,
and what engine/trade_plan.py reads from to generate TP/SL levels.
The more events you log via log_new_reaction(), the smarter these
averages get - this is the "grows smarter over time" feature.
"""

import statistics

from config import SPIKE_AVOID_SECONDS
from data.database import log_historical_reaction, get_historical_reactions
from data.prices import get_reaction_prices
from engine.deviation import calculate_deviation_score, classify_deviation
from engine.correlation import get_expected_direction


def _pct_move(price_start: float, price_end: float) -> float:
    """
    Calculate percentage move between two prices. Used as a
    universal "distance moved" metric across different asset types
    (forex pairs, gold, indices) since raw pip/point values aren't
    directly comparable across them.

    Args:
        price_start: Starting price.
        price_end: Ending price.

    Returns:
        Percentage change (e.g. 0.25 means +0.25%), or None if
        either price is missing.
    """
    if price_start is None or price_end is None or price_start == 0:
        return None
    return ((price_end - price_start) / price_start) * 100


def log_new_reaction(event_name: str, asset: str, actual: float, forecast: float,
                      event_datetime_utc) -> dict:
    """
    Given a completed event with a known actual number, fetch price
    data around the event and log a full historical reaction record.
    This is the main function to call right after an event's actual
    number is confirmed and enough time has passed (ideally 4+ hours
    later, so the 4hr move is known).

    Args:
        event_name: e.g. "NFP"
        asset: e.g. "EURUSD" (must be a key in config.ASSETS)
        actual: The actual released value.
        forecast: The forecasted value.
        event_datetime_utc: datetime of the release, in UTC.

    Returns:
        The reaction dict that was saved to the database.
    """
    deviation_result = calculate_deviation_score(actual, forecast, event_name=event_name)
    prices = get_reaction_prices(asset, event_datetime_utc)

    move_15min = _pct_move(prices["price_at_event"], prices["price_15min"])
    move_1hr = _pct_move(prices["price_at_event"], prices["price_1hr"])
    move_4hr = _pct_move(prices["price_at_event"], prices["price_4hr"])

    # Direction correctness: uses engine/correlation.py's real macro
    # relationships (e.g. NFP beat -> USD up -> EURUSD down) instead of
    # a blanket "beat = price up" assumption. If correlation.py reports
    # "Neutral" (context-dependent or unmapped), we skip accuracy scoring
    # for that asset rather than guessing.
    direction_correct = None
    if move_1hr is not None:
        expected = get_expected_direction(event_name, asset, deviation_result["raw_surprise"])
        if expected["direction"] != "Neutral":
            expected_positive = expected["direction"] == "Long"
            move_positive = move_1hr > 0
            direction_correct = 1 if expected_positive == move_positive else 0

    reaction = {
        "event_name": event_name,
        "asset": asset,
        "deviation_score": deviation_result["score"],
        "deviation_class": deviation_result["classification"],
        "move_15min": move_15min,
        "move_1hr": move_1hr,
        "move_4hr": move_4hr,
        "direction_correct": direction_correct,
        "event_datetime_utc": event_datetime_utc.isoformat()
            if hasattr(event_datetime_utc, "isoformat") else event_datetime_utc,
    }

    log_historical_reaction(reaction)
    return reaction


def get_event_statistics(event_name: str, asset: str = None) -> dict:
    """
    Compute summary statistics for a given event type (optionally
    filtered to one asset), based on everything logged so far.

    Args:
        event_name: e.g. "NFP"
        asset: optional, e.g. "EURUSD" - if provided, only that
               asset's reactions are included.

    Returns:
        A dict: {
            "sample_size": int,
            "avg_move_15min": float or None,
            "avg_move_1hr": float or None,
            "avg_move_4hr": float or None,
            "direction_accuracy_pct": float or None,
            "avoid_first_seconds": int (always SPIKE_AVOID_SECONDS),
        }
    """
    rows = get_historical_reactions(event_name)
    if asset:
        rows = [r for r in rows if r["asset"] == asset]

    if not rows:
        return {
            "sample_size": 0,
            "avg_move_15min": None,
            "avg_move_1hr": None,
            "avg_move_4hr": None,
            "direction_accuracy_pct": None,
            "avoid_first_seconds": SPIKE_AVOID_SECONDS,
        }

    def _avg(field):
        values = [r[field] for r in rows if r[field] is not None]
        return statistics.mean(values) if values else None

    accuracy_values = [r["direction_correct"] for r in rows if r["direction_correct"] is not None]
    accuracy_pct = (sum(accuracy_values) / len(accuracy_values) * 100) if accuracy_values else None

    return {
        "sample_size": len(rows),
        "avg_move_15min": _avg("move_15min"),
        "avg_move_1hr": _avg("move_1hr"),
        "avg_move_4hr": _avg("move_4hr"),
        "direction_accuracy_pct": accuracy_pct,
        "avoid_first_seconds": SPIKE_AVOID_SECONDS,
    }


def get_best_asset_for_event(event_name: str, candidate_assets: list) -> dict:
    """
    Among a list of candidate assets, determine which one has the
    most reliable (highest accuracy, most consistent) reaction to
    a given event type.

    Args:
        event_name: e.g. "NFP"
        candidate_assets: list of asset symbols to compare, e.g.
                           ["EURUSD", "XAUUSD", "US100"]

    Returns:
        A dict: {
            "best_asset": str or None,
            "stats_by_asset": {asset: get_event_statistics result, ...}
        }
        Returns best_asset=None if no asset has any logged history yet.
    """
    stats_by_asset = {}
    best_asset = None
    best_score = -1

    for asset in candidate_assets:
        stats = get_event_statistics(event_name, asset=asset)
        stats_by_asset[asset] = stats

        if stats["sample_size"] == 0 or stats["direction_accuracy_pct"] is None:
            continue

        # Simple ranking: prioritize direction accuracy, use sample
        # size as a tiebreaker so a 100%-accurate-on-1-sample asset
        # doesn't beat a 90%-accurate-on-20-samples asset unfairly.
        ranking_score = stats["direction_accuracy_pct"] + min(stats["sample_size"], 10)
        if ranking_score > best_score:
            best_score = ranking_score
            best_asset = asset

    return {"best_asset": best_asset, "stats_by_asset": stats_by_asset}