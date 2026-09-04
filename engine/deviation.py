"""
engine/deviation.py
--------------------
Calculates the "deviation score" when an actual economic number
is released, classifies it, and gives an instant read on expected
direction and confidence.

Deviation score formula:
    score = (actual - forecast) / historical_std_dev

Where historical_std_dev is the standard deviation of past
(actual - forecast) surprises for that same event type. If we
don't have enough history yet for an event, we fall back to a
simpler percentage-based method so the tool still works from day 1.
"""

import statistics

from config import DEVIATION_THRESHOLDS
from data.database import get_historical_reactions


def _get_historical_std_dev(event_name: str, min_samples: int = 5) -> float:
    """
    Calculate the standard deviation of past (actual - forecast)
    surprises for a given event, using data already logged in the
    historical_reactions table.

    Args:
        event_name: e.g. "NFP", "CPI"
        min_samples: minimum number of past records required before
                     we trust the calculated std dev.

    Returns:
        The standard deviation as a float, or None if not enough
        history exists yet.
    """
    rows = get_historical_reactions(event_name)
    scores = [row["deviation_score"] for row in rows if row["deviation_score"] is not None]

    if len(scores) < min_samples:
        return None

    return statistics.stdev(scores)


def calculate_deviation_score(actual: float, forecast: float, event_name: str = None,
                               fallback_std_dev: float = None) -> dict:
    """
    Calculate the deviation score for a news release.

    Args:
        actual: The actual released number.
        forecast: The forecasted/expected number.
        event_name: Event type, used to look up historical std dev
                    from the database if available.
        fallback_std_dev: Used if no historical std dev exists yet.
                           If not provided, a generic fallback based
                           on 10% of the forecast magnitude is used
                           (rough, but keeps the tool functional
                           before enough history is built up).

    Returns:
        A dict: {
            "raw_surprise": actual - forecast,
            "std_dev_used": the std dev value applied,
            "score": the calculated deviation score,
            "classification": one of "Major Beat", "Minor Beat",
                               "In Line", "Minor Miss", "Major Miss",
            "used_fallback": True if historical std dev wasn't available,
        }
    """
    raw_surprise = actual - forecast

    std_dev = None
    used_fallback = False

    if event_name:
        std_dev = _get_historical_std_dev(event_name)

    if std_dev is None or std_dev == 0:
        used_fallback = True
        if fallback_std_dev and fallback_std_dev > 0:
            std_dev = fallback_std_dev
        else:
            # Rough fallback: 10% of forecast magnitude, with a floor
            # to avoid division by zero on forecasts of 0.
            std_dev = max(abs(forecast) * 0.10, 0.01)

    score = raw_surprise / std_dev

    classification = classify_deviation(score)

    return {
        "raw_surprise": raw_surprise,
        "std_dev_used": std_dev,
        "score": score,
        "classification": classification,
        "used_fallback": used_fallback,
    }


def classify_deviation(score: float) -> str:
    """
    Classify a deviation score into a human-readable bucket.

    Args:
        score: The calculated deviation score.

    Returns:
        One of: "Major Beat", "Minor Beat", "In Line",
                "Minor Miss", "Major Miss"
    """
    if score >= DEVIATION_THRESHOLDS["major_beat"]:
        return "Major Beat"
    elif score >= DEVIATION_THRESHOLDS["minor_beat"]:
        return "Minor Beat"
    elif score > DEVIATION_THRESHOLDS["minor_miss"]:
        return "In Line"
    elif score > DEVIATION_THRESHOLDS["major_miss"]:
        return "Minor Miss"
    else:
        return "Major Miss"


def get_trade_recommendation(classification: str) -> dict:
    """
    Translate a deviation classification into a plain trade/no-trade
    signal with a confidence label.

    Args:
        classification: Output of classify_deviation().

    Returns:
        A dict: {
            "should_trade": bool,
            "confidence": "High" / "Medium" / "Low" / "None",
            "note": short explanation string
        }
    """
    mapping = {
        "Major Beat": {
            "should_trade": True,
            "confidence": "High",
            "note": "Strong beat - high probability directional move expected.",
        },
        "Minor Beat": {
            "should_trade": True,
            "confidence": "Medium",
            "note": "Modest beat - directional move likely but less explosive.",
        },
        "In Line": {
            "should_trade": False,
            "confidence": "None",
            "note": "Result matched expectations - no clear edge, best to stay out.",
        },
        "Minor Miss": {
            "should_trade": True,
            "confidence": "Medium",
            "note": "Modest miss - directional move likely but less explosive.",
        },
        "Major Miss": {
            "should_trade": True,
            "confidence": "High",
            "note": "Strong miss - high probability directional move expected.",
        },
    }
    return mapping.get(classification, {
        "should_trade": False, "confidence": "None", "note": "Unrecognized classification.",
    })