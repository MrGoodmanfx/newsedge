"""
engine/correlation.py
----------------------
Encodes how each asset actually reacts to each event type - this is
the fix for the direction-logic limitation flagged in historical.py
and trade_plan.py, where a blanket "beat = price up" assumption was
used as a placeholder.

Real macro relationships are directional and asset-specific:
  - A strong NFP/CPI beat usually strengthens the USD (hawkish signal).
  - USD strength means USD-quoted pairs like EURUSD, GBPUSD move DOWN.
  - USD strength means USD-base pairs like USDJPY move UP.
  - Gold (XAUUSD) is typically inversely correlated to USD strength/
    real yields, so a beat (hawkish) usually pushes gold DOWN.
  - Equity indices (US100/US500/US30) are genuinely mixed: a strong
    jobs/inflation beat can be read as "hawkish/bad for stocks" OR
    "economy strong/good for stocks" depending on the macro regime.
    We mark these as context-dependent rather than guessing.

This module is intentionally the single source of truth for
direction logic. historical.py and trade_plan.py both call into
this rather than each doing their own directional guessing.
"""

from config import EVENT_ASSET_MAP

# Multiplier convention:
#   +1  -> asset moves in the SAME direction as the surprise
#          (positive surprise/beat = price up)
#   -1  -> asset moves OPPOSITE to the surprise
#          (positive surprise/beat = price down)
#    0  -> relationship is context-dependent / not reliably directional
#          enough to encode as a simple rule (e.g. equities on jobs data)
#
# Keys are matched as case-insensitive substrings against the event name,
# same pattern as config._classify_tier, so "Non-Farm Employment Change"
# and "NFP" both match the "NFP" key.
CORRELATION_MAP = {
    "NFP": {
        "EURUSD": -1, "GBPUSD": -1, "USDJPY": 1,
        "XAUUSD": -1, "XAGUSD": -1,
        "US100": 0, "US500": 0, "US30": 0,   # mixed: hawkish vs. strong-economy reads
        "BTCUSDT": 0,
    },
    "CPI": {
        "EURUSD": -1, "GBPUSD": -1, "USDJPY": 1,
        "XAUUSD": -1, "XAGUSD": -1,
        "US100": -1, "US500": -1, "US30": -1,  # higher inflation -> rate hike fear -> stocks down
        "BTCUSDT": -1,
    },
    "FOMC": {
        "EURUSD": -1, "GBPUSD": -1, "USDJPY": 1,
        "XAUUSD": -1, "XAGUSD": -1,
        "US100": -1, "US500": -1, "US30": -1,  # hawkish surprise -> risk-off
        "BTCUSDT": -1,
    },
    "GDP": {
        "EURUSD": -1, "GBPUSD": -1, "USDJPY": 1,
        "XAUUSD": -1,
        "US100": 1, "US500": 1, "US30": 1,   # strong growth read as equity-positive
        "BTCUSDT": 1,
    },
    "PPI": {
        "EURUSD": -1, "GBPUSD": -1, "USDJPY": 1,
        "XAUUSD": -1, "XAGUSD": -1,
    },
    "RETAIL SALES": {
        "EURUSD": -1, "USDJPY": 1,
        "US100": 1, "US500": 1,
        "XAUUSD": -1,
    },
    "ISM MANUFACTURING": {
        "EURUSD": -1, "USDJPY": 1,
        "US100": 1, "US500": 1,
    },
    "CORE PCE": {
        "EURUSD": -1, "USDJPY": 1,
        "XAUUSD": -1, "US500": -1,
    },
}


def _match_event_key(event_name: str):
    """
    Find the CORRELATION_MAP key that matches the given event name,
    using the same substring-matching approach as config._classify_tier.

    Args:
        event_name: Raw event name, e.g. "Non-Farm Employment Change"

    Returns:
        The matching key string, or None if no match found.
    """
    name_lower = event_name.lower()
    for key in CORRELATION_MAP:
        if key.lower() in name_lower:
            return key
        # Also handle common aliases not literally contained in the name
        if key == "NFP" and ("non-farm" in name_lower or "nonfarm" in name_lower):
            return key
        if key == "FOMC" and "fed" in name_lower and ("rate" in name_lower or "statement" in name_lower):
            return key
    return None


def get_expected_direction(event_name: str, asset: str, raw_surprise: float):
    """
    Determine the expected price direction for an asset given a
    news surprise, using real macro correlation logic instead of
    a blanket assumption.

    Args:
        event_name: e.g. "Non-Farm Employment Change"
        asset: e.g. "EURUSD"
        raw_surprise: actual - forecast (positive = beat, negative = miss)

    Returns:
        A dict: {
            "direction": "Long" / "Short" / "Neutral",
            "multiplier_used": 1 / -1 / 0,
            "confidence_note": explanation string,
        }
        "Neutral" is returned when the relationship is context-dependent
        (multiplier 0) or when we have no mapping for this event/asset
        pair at all - in both cases, trade_plan.py should NOT auto-assume
        a direction and should flag lower confidence instead.
    """
    event_key = _match_event_key(event_name)

    if event_key is None or asset not in CORRELATION_MAP.get(event_key, {}):
        return {
            "direction": "Neutral",
            "multiplier_used": 0,
            "confidence_note": f"No correlation mapping for '{event_name}' x '{asset}' - "
                               f"direction unknown, treat with caution.",
        }

    multiplier = CORRELATION_MAP[event_key][asset]

    if multiplier == 0:
        return {
            "direction": "Neutral",
            "multiplier_used": 0,
            "confidence_note": f"{asset}'s reaction to {event_key} is context-dependent "
                               f"(can be read as hawkish-negative OR strong-economy-positive) "
                               f"- no reliable directional edge from surprise alone.",
        }

    surprise_sign = 1 if raw_surprise > 0 else -1
    result_sign = surprise_sign * multiplier

    direction = "Long" if result_sign > 0 else "Short"
    relationship = "same direction as surprise" if multiplier == 1 else "opposite direction to surprise"

    return {
        "direction": direction,
        "multiplier_used": multiplier,
        "confidence_note": f"{asset} typically moves {relationship} for {event_key} surprises.",
    }


def get_correlation_matrix(event_name: str) -> dict:
    """
    Build a full color-coded correlation matrix for an event, showing
    how every relevant asset is expected to react to a BEAT (positive
    surprise). Used to power the dashboard's correlation matrix view
    (feature #6 in the spec).

    Args:
        event_name: e.g. "Non-Farm Employment Change"

    Returns:
        A dict: {asset: {"color": "green"/"red"/"grey", "multiplier": int,
                          "note": str}, ...}
        green = asset expected up on a beat, red = expected down on a
        beat, grey = context-dependent/no reliable edge.
    """
    event_key = _match_event_key(event_name)
    matrix = {}

    # Use EVENT_ASSET_MAP (config.py) to know which assets are even
    # relevant to this event, falling back to CORRELATION_MAP's own
    # keys if no config entry exists.
    relevant_assets = None
    for map_key, assets in EVENT_ASSET_MAP.items():
        if map_key.lower() in event_name.lower():
            relevant_assets = assets
            break

    if relevant_assets is None and event_key:
        relevant_assets = list(CORRELATION_MAP[event_key].keys())
    elif relevant_assets is None:
        return {}

    for asset in relevant_assets:
        if event_key and asset in CORRELATION_MAP.get(event_key, {}):
            multiplier = CORRELATION_MAP[event_key][asset]
            if multiplier == 1:
                color, note = "green", f"{asset} typically rises on a {event_key} beat."
            elif multiplier == -1:
                color, note = "red", f"{asset} typically falls on a {event_key} beat."
            else:
                color, note = "grey", f"{asset}'s reaction to {event_key} is context-dependent."
        else:
            multiplier = None
            color, note = "grey", "No correlation data mapped for this asset/event pair."

        matrix[asset] = {"color": color, "multiplier": multiplier, "note": note}

    return matrix