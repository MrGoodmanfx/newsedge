"""
alerts/checklist.py
--------------------
Generates the pre-event discipline checklist (feature #7 in the spec).
30 minutes before every high-impact event, this builds a checklist the
trader should go through - spread check, open trade review, risk
limits, entry plan for BOTH beat and miss scenarios, TP/SL levels,
stop hunt zone, and position size.

This is deliberately a plain data structure (list of items with
descriptions) rather than anything interactive - the dashboard
(dashboard/app.py) will render it as actual checkboxes. Keeping the
logic here means the same checklist can also be sent via Telegram
as plain text.
"""

from engine.trade_plan import generate_trade_plan
from engine.correlation import get_expected_direction


def generate_pre_event_checklist(event_name: str, asset: str, forecast: float,
                                  account_balance: float = None) -> dict:
    """
    Build a pre-event checklist for a specific event/asset pair.
    Generates BOTH a "if beat" and "if miss" mini trade plan so the
    trader walks in prepared for either outcome, per the spec.

    Args:
        event_name: e.g. "Non-Farm Employment Change"
        asset: e.g. "EURUSD"
        forecast: The forecasted value for the event (used to simulate
                  a beat and a miss scenario for planning purposes).
        account_balance: Optional, used to pre-calculate position sizing
                          hints for both scenarios.

    Returns:
        A dict: {
            "event_name": str, "asset": str,
            "checklist_items": [ {"item": str, "checked": False}, ... ],
            "beat_scenario": direction/note info if forecast is beaten,
            "miss_scenario": direction/note info if forecast is missed,
        }
    """
    # Simulate a moderate beat/miss (10% above/below forecast) purely to
    # show the trader which direction each outcome implies - NOT a
    # prediction of what will actually happen.
    simulated_beat = forecast * 1.10 if forecast != 0 else 1
    simulated_miss = forecast * 0.90 if forecast != 0 else -1

    beat_direction = get_expected_direction(event_name, asset, simulated_beat - forecast)
    miss_direction = get_expected_direction(event_name, asset, simulated_miss - forecast)

    checklist_items = [
        {"item": f"Spread on {asset} is acceptable for news volatility?", "checked": False},
        {"item": "Any open trades on this or correlated assets that need closing before the news?", "checked": False},
        {"item": "Account risk within your daily/weekly limits before adding this trade?", "checked": False},
        {"item": f"Entry plan ready for a BEAT: {beat_direction['direction']} "
                 f"({beat_direction['confidence_note']})", "checked": False},
        {"item": f"Entry plan ready for a MISS: {miss_direction['direction']} "
                 f"({miss_direction['confidence_note']})", "checked": False},
        {"item": "TP and SL levels understood for both scenarios (will be finalized once actual is known)?", "checked": False},
        {"item": "Stop hunt / spike zone identified - will NOT enter in first 60 seconds?", "checked": False},
        {"item": "Position size calculated based on your risk %?", "checked": False},
    ]

    result = {
        "event_name": event_name,
        "asset": asset,
        "checklist_items": checklist_items,
        "beat_scenario": beat_direction,
        "miss_scenario": miss_direction,
    }

    return result


def checklist_to_text(checklist: dict) -> str:
    """
    Render a checklist dict as a plain-text message, suitable for
    sending via Telegram or printing to console.

    Args:
        checklist: Output of generate_pre_event_checklist().

    Returns:
        A formatted multi-line string.
    """
    lines = [
        f"PRE-EVENT CHECKLIST",
        f"Event: {checklist['event_name']}",
        f"Asset: {checklist['asset']}",
        "",
        f"If BEAT -> {checklist['beat_scenario']['direction']}: "
        f"{checklist['beat_scenario']['confidence_note']}",
        f"If MISS -> {checklist['miss_scenario']['direction']}: "
        f"{checklist['miss_scenario']['confidence_note']}",
        "",
        "Checklist:",
    ]
    for item in checklist["checklist_items"]:
        box = "[x]" if item["checked"] else "[ ]"
        lines.append(f"  {box} {item['item']}")

    return "\n".join(lines)