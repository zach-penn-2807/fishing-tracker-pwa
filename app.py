import streamlit as st

from src.ui.pwa_helper import inject_pwa_head
from src.database.db import init_db
from src.ui.log_tab import render_log_tab
from src.ui.map_tab import render_map_tab
from src.ui.stats_tab import render_stats_tab

st.set_page_config(
    page_title="Dad's Catch Log",
    page_icon="🎣",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .stButton > button {
        min-height: 3.4rem;
        font-size: 1.15rem;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

init_db()

inject_pwa_head()

st.title("🎣 Catch Log")

tab_log, tab_map, tab_stats = st.tabs(["Log Catch", "Map & Spots", "Trips & Stats"])

with tab_log:
    render_log_tab()

with tab_map:
    render_map_tab()

with tab_stats:
    render_stats_tab()