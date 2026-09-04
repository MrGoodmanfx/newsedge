"""
dashboard/app.py
-----------------
NewsEdge Streamlit Dashboard.

Run with: streamlit run dashboard/app.py (from the newsedge folder)

Shows:
  - This week's calendar (EAT), with High-impact events highlighted
  - Live countdown to the next High-impact event
  - Manual deviation calculator + instant trade plan generator
  - Asset correlation matrix for a selected event
  - Post-event trade log / win rate stats

This file only handles DISPLAY logic - all the real calculations
live in engine/ and data/, imported here.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from datetime import datetime
import pytz

from config import ASSETS
from data.database import init_db, get_upcoming_events, get_trade_log
from data.calendar import refresh_calendar
from utils.timezone import utc_to_eat, format_eat, time_until, eat_now
from engine.deviation import calculate_deviation_score, get_trade_recommendation
from engine.trade_plan import generate_trade_plan
from engine.correlation import get_correlation_matrix
from alerts.checklist import generate_pre_event_checklist, checklist_to_text

st.set_page_config(page_title="NEWSEDGE.AI | G Trader Quantum", layout="wide", initial_sidebar_state="expanded")

# ---------------------------------------------------------
# BRAND STYLING - VantEdge.AI-inspired dark/red tech theme
# ---------------------------------------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@500;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Rajdhani', sans-serif;
    }

    .stApp {
        background-color: #060607;
        background-image:
            linear-gradient(rgba(255,0,40,0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,0,40,0.035) 1px, transparent 1px);
        background-size: 42px 42px;
    }

    /* Brand header */
    .ne-header { text-align: center; padding: 18px 0 6px 0; }
    .ne-title {
        font-family: 'Share Tech Mono', monospace;
        font-size: 3.2rem;
        font-weight: 700;
        color: #f2f2f2;
        letter-spacing: 6px;
        margin: 0;
    }
    .ne-title .accent {
        color: #ff1a2e;
        text-shadow: 0 0 18px rgba(255,26,46,0.75), 0 0 40px rgba(255,26,46,0.35);
    }
    .ne-subtitle {
        font-family: 'Share Tech Mono', monospace;
        color: #6b7280;
        letter-spacing: 4px;
        font-size: 0.85rem;
        margin-top: 4px;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #0a0a0c;
        border-right: 1px solid #2a0a0e;
    }
    section[data-testid="stSidebar"] * { font-family: 'Share Tech Mono', monospace; }

    /* Metrics */
    div[data-testid="stMetric"] {
        background: linear-gradient(180deg, rgba(255,26,46,0.06), rgba(0,0,0,0));
        border: 1px solid rgba(255,26,46,0.35);
        border-radius: 6px;
        padding: 10px 14px;
    }
    div[data-testid="stMetricLabel"] {
        font-family: 'Share Tech Mono', monospace;
        color: #9ca3af !important;
        letter-spacing: 1px;
        text-transform: uppercase;
        font-size: 0.75rem !important;
    }
    div[data-testid="stMetricValue"] { color: #f2f2f2 !important; }

    /* Buttons */
    .stButton > button {
        font-family: 'Share Tech Mono', monospace;
        letter-spacing: 2px;
        text-transform: uppercase;
        background-color: #0a0a0c;
        color: #ff1a2e;
        border: 1px dashed #ff1a2e;
        border-radius: 6px;
    }
    .stButton > button:hover {
        background-color: rgba(255,26,46,0.12);
        color: #ffffff;
        border-color: #ff1a2e;
    }

    /* Headings */
    h1, h2, h3 {
        font-family: 'Share Tech Mono', monospace !important;
        letter-spacing: 2px;
        color: #f2f2f2 !important;
    }

    /* Info/warning boxes */
    div[data-testid="stAlert"] {
        border: 1px dashed rgba(255,26,46,0.5);
        background-color: rgba(255,26,46,0.05);
    }

    /* Text/number inputs - match dark theme */
    .stTextInput input, .stNumberInput input {
        background-color: #0a0a0c !important;
        color: #f2f2f2 !important;
        border: 1px solid rgba(255,26,46,0.35) !important;
        font-family: 'Share Tech Mono', monospace !important;
    }
    .stSelectbox div[data-baseweb="select"] > div {
        background-color: #0a0a0c !important;
        border: 1px solid rgba(255,26,46,0.35) !important;
        color: #f2f2f2 !important;
    }

    /* Correlation matrix cards - prevent asset name wrapping */
    .ne-corr-card b { white-space: nowrap; font-size: 1.05rem; }
</style>""", unsafe_allow_html=True)

st.markdown("""
<div class="ne-header">
    <div class="ne-title">NEWS<span class="accent">EDGE</span>.AI</div>
    <div class="ne-subtitle">// REAL-TIME NEWS EVENT INTELLIGENCE ENGINE — G TRADER QUANTUM</div>
</div>
""", unsafe_allow_html=True)

init_db()

# ---------------------------------------------------------
# SIDEBAR - Global controls
# ---------------------------------------------------------
st.sidebar.markdown("**NEWSEDGE.AI**")
st.sidebar.caption("// G TRADER QUANTUM")
st.sidebar.markdown(f"**TIME (EAT):** `{eat_now().strftime('%Y-%m-%d %H:%M:%S')}`")

if st.sidebar.button("Refresh Calendar Now"):
    with st.spinner("Fetching latest calendar..."):
        count = refresh_calendar()
    st.sidebar.success(f"Refreshed - {count} events loaded.")

page = st.sidebar.radio(
    "Navigate",
    ["This Week's Calendar", "Trade Plan Generator", "Correlation Matrix", "Trade Journal"],
)

# ---------------------------------------------------------
# PAGE: THIS WEEK'S CALENDAR
# ---------------------------------------------------------
if page == "This Week's Calendar":
    st.title("This Week's Economic Calendar")

    events = get_upcoming_events(limit=200)
    if not events:
        st.warning("No events loaded yet. Click 'Refresh Calendar Now' in the sidebar.")
    else:
        rows = []
        next_high_impact = None
        now_utc = datetime.now(pytz.utc)

        for e in events:
            event_dt_utc = datetime.fromisoformat(e["event_datetime_utc"])
            if event_dt_utc.tzinfo is None:
                event_dt_utc = pytz.utc.localize(event_dt_utc)
            event_dt_eat = utc_to_eat(event_dt_utc)

            if e["impact_level"] == "High" and event_dt_utc > now_utc and next_high_impact is None:
                next_high_impact = (e, event_dt_eat)

            rows.append({
                "Event": e["event_name"],
                "Tier": e["event_tier"],
                "Impact": e["impact_level"],
                "Date (EAT)": format_eat(event_dt_eat, "%a %d %b, %H:%M"),
                "Previous": e["previous_value"],
                "Forecast": e["forecast_value"],
                "Actual": e["actual_value"],
                "Assets": e["affected_assets"],
            })

        # Countdown banner
        if next_high_impact:
            event, event_eat = next_high_impact
            countdown = time_until(event_eat)
            st.info(
                f"**Next High-Impact Event:** {event['event_name']} — "
                f"{format_eat(event_eat, '%a %d %b, %H:%M')} EAT "
                f"(in {countdown['days']}d {countdown['hours']}h {countdown['minutes']}m)"
            )

        df = pd.DataFrame(rows)

        def _highlight_high_impact(row):
            if row["Impact"] == "High":
                return ["background-color: #3a1f1f"] * len(row)
            return [""] * len(row)

        st.dataframe(df.style.apply(_highlight_high_impact, axis=1), use_container_width=True, height=500)

# ---------------------------------------------------------
# PAGE: TRADE PLAN GENERATOR
# ---------------------------------------------------------
elif page == "Trade Plan Generator":
    st.title("Trade Plan Generator")
    st.caption("Enter the actual number the moment it releases to get an instant plan.")

    col1, col2 = st.columns(2)
    with col1:
        event_name = st.text_input("Event Name", value="Non-Farm Employment Change")
        asset = st.selectbox("Asset", list(ASSETS.keys()))
        forecast = st.number_input("Forecast Value", value=180000.0, format="%.2f")
        actual = st.number_input("Actual Value", value=180000.0, format="%.2f")
    with col2:
        account_balance = st.number_input("Account Balance ($)", value=1000.0, min_value=0.0)
        risk_percent = st.number_input("Risk % Per Trade", value=1.0, min_value=0.1, max_value=10.0)

    if st.button("Generate Trade Plan", type="primary"):
        with st.spinner("Analyzing..."):
            plan = generate_trade_plan(
                event_name, asset, actual, forecast,
                account_balance=account_balance, risk_percent=risk_percent,
            )

        st.divider()

        if not plan.get("should_trade", False):
            st.warning(f"**No Trade Signal** — {plan.get('reason_no_trade', plan.get('note', ''))}")
            st.metric("Deviation Score", f"{plan['deviation']['score']:.2f}", plan['deviation']['classification'])
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Direction", plan["direction"])
            m2.metric("Deviation Score", f"{plan['deviation']['score']:.2f}")
            m3.metric("Classification", plan["deviation"]["classification"])
            m4.metric("Confidence", plan["confidence"])

            st.caption(plan.get("direction_note", ""))

            if plan.get("used_generic_estimate"):
                st.info(
                    f"Historical sample size: {plan.get('historical_sample_size', 0)} — "
                    f"using generic estimated move sizes until more data is logged."
                )

            st.subheader("Trade Levels")
            l1, l2, l3, l4, l5 = st.columns(5)
            l1.metric("Entry Zone", plan.get("entry_zone", "N/A"))
            l2.metric("TP1", plan.get("tp1", "N/A"))
            l3.metric("TP2", plan.get("tp2", "N/A"))
            l4.metric("TP3", plan.get("tp3", "N/A"))
            l5.metric("Stop Loss", plan.get("stop_loss", "N/A"))

            st.write(f"**Risk/Reward (TP1):** {plan.get('risk_reward_tp1', 'N/A')}")
            st.write(f"**Wait before entry:** {plan.get('wait_before_entry_seconds', 60)} seconds "
                     f"(spike/manipulation window)")
            st.write(f"**Time-based exit:** {plan.get('time_based_exit_hours', 4)} hours if no TP hit")

            if "position_sizing" in plan:
                sizing = plan["position_sizing"]
                st.subheader("Position Sizing")
                s1, s2, s3 = st.columns(3)
                s1.metric("Risk Amount", f"${sizing['risk_amount']:.2f}")
                s2.metric("Stop Distance", f"{sizing['stop_distance']:.5f}")
                s3.metric("Position Size (units)", f"{sizing['position_size_units']:.2f}")

    st.divider()
    st.subheader("Pre-Event Checklist")
    if st.button("Generate Checklist for This Event"):
        checklist = generate_pre_event_checklist(event_name, asset, forecast, account_balance)
        st.text(checklist_to_text(checklist))

# ---------------------------------------------------------
# PAGE: CORRELATION MATRIX
# ---------------------------------------------------------
elif page == "Correlation Matrix":
    st.title("Asset Correlation Matrix")
    event_name = st.text_input("Event Name", value="Non-Farm Employment Change", key="corr_event")

    matrix = get_correlation_matrix(event_name)
    if not matrix:
        st.warning("No correlation data mapped for this event name. Try NFP, CPI, FOMC, GDP, PPI, or Retail Sales.")
    else:
        cols = st.columns(len(matrix))
        color_map = {"green": "#0d3d1f", "red": "#3d0d14", "grey": "#1a1a1c"}
        border_map = {"green": "#22c55e", "red": "#ff1a2e", "grey": "#4b5563"}
        for col, (asset, info) in zip(cols, matrix.items()):
            with col:
                st.markdown(
                    f"<div class='ne-corr-card' style='background-color:{color_map[info['color']]}; "
                    f"border: 1px dashed {border_map[info['color']]}; "
                    f"font-family: \"Share Tech Mono\", monospace; letter-spacing:1px; "
                    f"padding:16px; border-radius:6px; text-align:center; color:#f2f2f2;'>"
                    f"<b>{asset}</b><br>{info['color'].upper()}</div>",
                    unsafe_allow_html=True,
                )
                st.caption(info["note"])

# ---------------------------------------------------------
# PAGE: TRADE JOURNAL
# ---------------------------------------------------------
elif page == "Trade Journal":
    st.title("Trade Journal")

    trades = get_trade_log()
    if not trades:
        st.info("No trades logged yet. Trades logged via engine/historical.py or the API will appear here.")
    else:
        rows = [dict(t) for t in trades]
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)

        if "outcome" in df.columns:
            win_rate = (df["outcome"] == "win").mean() * 100 if len(df) > 0 else 0
            st.metric("Win Rate", f"{win_rate:.1f}%")