"""
engine/trade_plan.py
---------------------
Generates a complete, actionable trade plan the moment a news
event's actual number is known.

Combines:
  - engine/deviation.py  -> is this worth trading, and which direction?
  - engine/historical.py -> how far has this asset typically moved
                             after this event, historically?
  - config.py             -> risk settings, spike-avoidance window

Note: direction here uses the SAME placeholder logic flagged in
historical.py (positive surprise = price up). This will be corrected
once engine/correlation.py encodes real per-asset direction logic -
at that point, trade_plan.py's direction lookup will be updated to
pull from correlation.py instead of guessing.
"""

from config import SPIKE_AVOID_SECONDS, ENTRY_WINDOW_SECONDS, DEFAULT_RISK_PERCENT, TIME_EXIT_HOURS
from engine.deviation import calculate_deviation_score, get_trade_recommendation
from engine.historical import get_event_statistics
from engine.correlation import get_expected_direction
from data.prices import get_latest_price


def _pct_to_price_distance(current_price: float, pct_move: float) -> float:
    """
    Convert a historical percentage move into an absolute price
    distance for the asset's current price level.

    Args:
        current_price: The asset's current price.
        pct_move: A percentage move, e.g. 0.25 for +0.25%.

    Returns:
        The absolute price distance (always positive - direction is
        applied separately when building TP/SL levels).
    """
    if current_price is None or pct_move is None:
        return None
    return abs(current_price * (pct_move / 100))


def calculate_position_size(account_balance: float, risk_percent: float,
                             entry_price: float, stop_loss_price: float) -> dict:
    """
    Calculate position size based on account risk percentage.

    Args:
        account_balance: Total account balance in account currency.
        risk_percent: % of account to risk on this trade (e.g. 1.0).
        entry_price: Planned entry price.
        stop_loss_price: Planned stop loss price.

    Returns:
        A dict: {
            "risk_amount": account_balance * risk_percent / 100,
            "stop_distance": abs(entry_price - stop_loss_price),
            "position_size_units": risk_amount / stop_distance,
        }
        position_size_units is in "price units" (e.g. for forex this
        translates to lot size via your broker's contract specs -
        this gives you the raw unit count to convert).
    """
    risk_amount = account_balance * (risk_percent / 100)
    stop_distance = abs(entry_price - stop_loss_price)

    if stop_distance == 0:
        return {"risk_amount": risk_amount, "stop_distance": 0, "position_size_units": 0}

    position_size_units = risk_amount / stop_distance

    return {
        "risk_amount": risk_amount,
        "stop_distance": stop_distance,
        "position_size_units": position_size_units,
    }


def generate_trade_plan(event_name: str, asset: str, actual: float, forecast: float,
                         account_balance: float = None, risk_percent: float = None) -> dict:
    """
    Generate a complete trade plan for a news event that just released.

    Args:
        event_name: e.g. "NFP"
        asset: e.g. "EURUSD" (must be a key in config.ASSETS)
        actual: The actual released value.
        forecast: The forecasted value.
        account_balance: Optional - if provided along with risk_percent,
                          position size is calculated.
        risk_percent: Optional - % of account to risk (defaults to
                      config.DEFAULT_RISK_PERCENT if account_balance given).

    Returns:
        A dict containing the full trade plan - direction, wait time,
        entry zone, TP1/2/3, stop loss, risk/reward, position size,
        and time-based exit. If classification is "In Line", the plan
        will indicate should_trade=False and skip level calculations.
    """
    deviation = calculate_deviation_score(actual, forecast, event_name=event_name)
    recommendation = get_trade_recommendation(deviation["classification"])

    plan = {
        "event_name": event_name,
        "asset": asset,
        "deviation": deviation,
        "should_trade": recommendation["should_trade"],
        "confidence": recommendation["confidence"],
        "note": recommendation["note"],
    }

    if not recommendation["should_trade"]:
        plan["reason_no_trade"] = "Result was in line with forecast - no tradeable edge."
        return plan

    # Direction: uses engine/correlation.py's real macro relationships
    # rather than a blanket "beat = price up" assumption.
    direction_info = get_expected_direction(event_name, asset, deviation["raw_surprise"])
    direction = direction_info["direction"]
    plan["direction_note"] = direction_info["confidence_note"]

    if direction == "Neutral":
        plan["should_trade"] = False
        plan["reason_no_trade"] = ("No reliable directional edge for this asset/event pair "
                                    "(context-dependent relationship) - skipping trade plan.")
        return plan

    plan["direction"] = direction

    # Pull historical stats for this event+asset to size TP levels realistically.
    stats = get_event_statistics(event_name, asset=asset)
    plan["historical_sample_size"] = stats["sample_size"]

    current_price = get_latest_price(asset)
    plan["current_price"] = current_price

    if current_price is None:
        plan["warning"] = "Could not fetch current price - TP/SL levels unavailable."
        return plan

    # Convert historical % moves into price distances. If we don't have
    # ENOUGH samples to trust the averages (same 5-sample threshold used
    # in deviation.py), use generic estimates for ALL THREE timeframes
    # together - never mix real and generic data across timeframes, since
    # that can produce nonsensical results (e.g. TP1 farther than TP2).
    MIN_RELIABLE_SAMPLES = 5
    generic_estimate_used = stats["sample_size"] < MIN_RELIABLE_SAMPLES

    if generic_estimate_used:
        move_15, move_1h, move_4h = 0.3, 0.6, 1.0
    else:
        move_15 = stats["avg_move_15min"] if stats["avg_move_15min"] is not None else 0.3
        move_1h = stats["avg_move_1hr"] if stats["avg_move_1hr"] is not None else 0.6
        move_4h = stats["avg_move_4hr"] if stats["avg_move_4hr"] is not None else 1.0

    dist_15 = _pct_to_price_distance(current_price, move_15)
    dist_1h = _pct_to_price_distance(current_price, move_1h)
    dist_4h = _pct_to_price_distance(current_price, move_4h)

    sign = 1 if direction == "Long" else -1

    # Entry zone: historically, price spikes then retraces before the
    # real move continues. We estimate the entry zone as a small
    # retrace (25% of the 15-min move) back toward the pre-event price.
    entry_retrace = dist_15 * 0.25
    entry_price = current_price - (sign * entry_retrace)

    tp1 = entry_price + (sign * dist_15)
    tp2 = entry_price + (sign * dist_1h)
    tp3 = entry_price + (sign * dist_4h)

    # Stop loss: placed beyond the initial spike/retrace zone, using
    # 50% of the 15-min move as a buffer against the manipulation wick.
    stop_loss = entry_price - (sign * dist_15 * 0.5)

    risk = abs(entry_price - stop_loss)
    reward_tp1 = abs(tp1 - entry_price)
    risk_reward_tp1 = round(reward_tp1 / risk, 2) if risk > 0 else None

    plan.update({
        "wait_before_entry_seconds": SPIKE_AVOID_SECONDS,
        "entry_window_seconds": ENTRY_WINDOW_SECONDS,
        "entry_zone": round(entry_price, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "stop_loss": round(stop_loss, 5),
        "risk_reward_tp1": risk_reward_tp1,
        "time_based_exit_hours": TIME_EXIT_HOURS,
        "used_generic_estimate": generic_estimate_used,
    })

    if account_balance is not None:
        risk_pct = risk_percent if risk_percent is not None else DEFAULT_RISK_PERCENT
        sizing = calculate_position_size(account_balance, risk_pct, entry_price, stop_loss)
        plan["position_sizing"] = sizing

    return plan