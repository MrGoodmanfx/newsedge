"""
alerts/telegram.py
-------------------
Sends alerts to your Telegram chat at key moments (feature #9 in spec):
  - 1 hour before a high-impact event: preparation alert
  - 30 minutes before: checklist alert
  - 5 minutes before: final warning
  - The moment actual drops: deviation score + trade plan
  - Entry window open: 60-90s after release, safe to enter

Uses plain HTTP requests to Telegram's Bot API rather than the
python-telegram-bot library's full async framework, since we only
need simple "send a message" functionality - keeps this module
lightweight and easy to call from anywhere (main.py, dashboard, etc.)
without needing an event loop.
"""

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_API_BASE = "https://api.telegram.org"


def send_telegram_message(text: str) -> bool:
    """
    Send a plain text message to the configured Telegram chat.

    Args:
        text: The message content. Supports basic Markdown if you
              wrap words in *bold* or _italic_.

    Returns:
        True if the message was sent successfully, False otherwise
        (including the case where no token/chat ID is configured -
        in that case we print a warning instead of crashing, so
        NewsEdge keeps working even before you set up Telegram).
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[telegram.py] Skipping alert - TELEGRAM_BOT_TOKEN or "
              "TELEGRAM_CHAT_ID not set in environment variables.")
        return False

    url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[telegram.py] Failed to send Telegram message: {e}")
        return False


def send_preparation_alert(event_name: str, minutes_until: int):
    """
    Send the 1-hour-before preparation alert.

    Args:
        event_name: e.g. "Non-Farm Employment Change"
        minutes_until: minutes remaining until the event.
    """
    text = (
        f"*NewsEdge - Preparation Alert*\n"
        f"{event_name} releases in {minutes_until} minutes.\n"
        f"Start reviewing your pre-event checklist."
    )
    return send_telegram_message(text)


def send_checklist_alert(checklist_text: str):
    """
    Send the 30-minutes-before checklist alert.

    Args:
        checklist_text: Pre-formatted text from
                         alerts.checklist.checklist_to_text().
    """
    text = f"*NewsEdge - 30 Min Checklist*\n\n{checklist_text}"
    return send_telegram_message(text)


def send_final_warning(event_name: str):
    """
    Send the 5-minutes-before final warning alert.

    Args:
        event_name: e.g. "Non-Farm Employment Change"
    """
    text = (
        f"*NewsEdge - FINAL WARNING*\n"
        f"{event_name} releases in 5 minutes.\n"
        f"Close unrelated trades. Get ready."
    )
    return send_telegram_message(text)


def send_trade_plan_alert(plan: dict):
    """
    Send the instant deviation score + trade plan the moment the
    actual number is known.

    Args:
        plan: Output dict from engine.trade_plan.generate_trade_plan().
    """
    if not plan.get("should_trade", False):
        text = (
            f"*NewsEdge - {plan['event_name']}*\n"
            f"Result: {plan['deviation']['classification']}\n"
            f"{plan.get('reason_no_trade', plan.get('note', 'No trade signal.'))}"
        )
        return send_telegram_message(text)

    text = (
        f"*NewsEdge - {plan['event_name']} ({plan['asset']})*\n"
        f"Deviation: {plan['deviation']['classification']} "
        f"(score: {plan['deviation']['score']:.2f})\n"
        f"Direction: *{plan['direction']}*\n"
        f"Confidence: {plan['confidence']}\n\n"
        f"Entry Zone: {plan.get('entry_zone', 'N/A')}\n"
        f"TP1: {plan.get('tp1', 'N/A')}\n"
        f"TP2: {plan.get('tp2', 'N/A')}\n"
        f"TP3: {plan.get('tp3', 'N/A')}\n"
        f"Stop Loss: {plan.get('stop_loss', 'N/A')}\n"
        f"R:R (TP1): {plan.get('risk_reward_tp1', 'N/A')}\n\n"
        f"Wait {plan.get('wait_before_entry_seconds', 60)}s before entering "
        f"(spike/manipulation window)."
    )
    return send_telegram_message(text)


def send_entry_window_alert(asset: str):
    """
    Send the "entry window open" alert, 60-90s after release.

    Args:
        asset: e.g. "EURUSD"
    """
    text = (
        f"*NewsEdge - Entry Window Open*\n"
        f"{asset}: Spike window has passed. Safe to enter now."
    )
    return send_telegram_message(text)