import streamlit as st

from src.database.db import init_db
from src.ui.analytics_tab import render_analytics_tab
from src.ui.log_tab import render_log_tab
from src.ui.pwa_helper import inject_pwa_head
from src.ui.sessions_tab import render_sessions_tab

st.set_page_config(
    page_title="Carp Session & Swim Tracker",
    page_icon="🎣",
    layout="centered",
    initial_sidebar_state="collapsed",
)

inject_pwa_head()
init_db()

st.markdown(
    """
    <style>
        div.stButton > button {
            min-height: 48px;
            font-weight: 600;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

title_col, unit_col = st.columns([2.2, 1.3])
with title_col:
    st.title("🎣 Carp & Swim Log")
with unit_col:
    primary_unit = st.radio(
        "Display Units",
        options=["lb", "kg"],
        format_func=lambda u: "lb / oz" if u == "lb" else "kg",
        horizontal=True,
        key="global_unit_toggle",
    )

tab_log, tab_sessions, tab_explore = st.tabs(["Log", "Sessions", "Explore"])

with tab_log:
    render_log_tab()

with tab_sessions:
    render_sessions_tab(primary_unit=primary_unit)

with tab_explore:
    render_analytics_tab(primary_unit=primary_unit)