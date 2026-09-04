"""
config.py
---------
Central configuration for NewsEdge.
Every other module imports settings from here so there is
ONE place to change assets, timezones, thresholds, and keys.
"""

import os

# ---------------------------------------------------------
# TIMEZONE SETTINGS
# ---------------------------------------------------------
# Kenya (EAT) is UTC+3, no daylight saving changes.
EAT_TIMEZONE = "Africa/Nairobi"

# ---------------------------------------------------------
# ASSETS WE TRACK
# ---------------------------------------------------------
# Each asset maps to the yfinance ticker symbol used to pull
# price data. Some assets (indices) use special Yahoo symbols.
ASSETS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "XAUUSD": "GC=F",       # Gold futures (proxy for XAUUSD)
    "XAGUSD": "SI=F",       # Silver futures (proxy for XAGUSD)
    "US100": "^NDX",        # Nasdaq 100
    "US500": "^GSPC",       # S&P 500
    "US30": "^DJI",         # Dow Jones
    "BTCUSDT": "BTC-USD",   # Crypto (also available via ccxt)
}

# ---------------------------------------------------------
# EVENT TIERS
# ---------------------------------------------------------
# Used to prioritize which events get full trade-plan treatment
# vs. which are just logged for awareness.
TIER_1_EVENTS = [
    "Non-Farm Payrolls",
    "NFP",
    "CPI",
    "Consumer Price Index",
    "FOMC Statement",
    "FOMC Meeting Minutes",
    "Fed Interest Rate Decision",
    "Fed Chair Press Conference",
]

TIER_2_EVENTS = [
    "GDP",
    "PPI",
    "Producer Price Index",
    "Retail Sales",
    "Unemployment Claims",
    "ISM Manufacturing PMI",
    "ISM Services PMI",
    "Core PCE Price Index",
]

TIER_3_EVENTS = [
    "ADP Employment Change",
    "Trade Balance",
    "Consumer Confidence",
    "Building Permits",
]

# ---------------------------------------------------------
# EVENT -> ASSET REACTION MAP
# ---------------------------------------------------------
# Which assets are most sensitive to each event type.
# Used by engine/correlation.py to decide what to display.
EVENT_ASSET_MAP = {
    "NFP": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US100", "US500", "US30"],
    "CPI": ["EURUSD", "XAUUSD", "US100", "US500"],
    "FOMC Statement": ["EURUSD", "XAUUSD", "US100", "US500", "US30", "BTCUSDT"],
    "GDP": ["EURUSD", "US500"],
    "PPI": ["XAUUSD", "EURUSD"],
    "Retail Sales": ["US100", "US500", "EURUSD"],
    "ISM Manufacturing PMI": ["US100", "US500", "EURUSD"],
    "Core PCE Price Index": ["XAUUSD", "EURUSD", "US500"],
}

# ---------------------------------------------------------
# DEVIATION SCORE THRESHOLDS
# ---------------------------------------------------------
# score = (actual - forecast) / historical_std_dev
DEVIATION_THRESHOLDS = {
    "major_beat": 1.5,
    "minor_beat": 0.5,
    "minor_miss": -0.5,
    "major_miss": -1.5,
}

# ---------------------------------------------------------
# TRADE PLAN DEFAULTS
# ---------------------------------------------------------
SPIKE_AVOID_SECONDS = 60          # Do not enter within this window after release
ENTRY_WINDOW_SECONDS = 90         # Suggested wait time before entry
DEFAULT_RISK_PERCENT = 1.0        # Default % of account risked per trade
TIME_EXIT_HOURS = 4               # Exit trade if no TP hit within this many hours

# ---------------------------------------------------------
# FILE PATHS
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "data", "newsedge.db")

# ---------------------------------------------------------
# TELEGRAM SETTINGS
# ---------------------------------------------------------
# Fill these in once you create a Telegram bot via @BotFather.
# Leave as empty strings for now - Telegram alerts will just be
# skipped (with a warning) until these are set.
TELEGRAM_BOT_TOKEN = os.environ.get("NEWSEDGE_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("NEWSEDGE_TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------
# CALENDAR SETTINGS
# ---------------------------------------------------------
CALENDAR_REFRESH_MINUTES = 15     # How often to refresh the economic calendar
IMPACT_LEVELS = ["High", "Medium", "Low"]