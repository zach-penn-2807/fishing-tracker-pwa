from datetime import datetime
import streamlit as st

from src.database.db import get_all_sessions, get_session_stints, query_catches
from src.ui.formatting import (
    format_carp_ratio,
    format_duration,
    format_time_window,
    format_weight,
)
from src.utils.moon import format_moon_label


def render_sessions_tab(primary_unit: str = "lb") -> None:
    """Render Tab 2: Session summary, swim timeline windows, and session catch list."""
    sessions = get_all_sessions()
    if not sessions:
        st.info("No sessions logged yet. Start your first session in the Log tab!")
        return

    session_labels = {
        s["id"]: (
            f"{s['lake_name']} — {datetime.fromisoformat(s['start_time']).strftime('%d %b %Y %H:%M')} "
            f"({'Active' if not s['end_time'] else 'Closed'} • {s['total_catches']} carp)"
        )
        for s in sessions
    }

    selected_id = st.selectbox(
        "Select Session",
        options=[s["id"] for s in sessions],
        format_func=lambda sid: session_labels[sid],
    )

    session = next(s for s in sessions if s["id"] == selected_id)
    stints = get_session_stints(selected_id)
    catches = query_catches(session_id=selected_id)

    # --- 1. SESSION SUMMARY KPIs ---
    m1, m2, m3 = st.columns(3)
    m1.metric("Session Length", format_duration(session["start_time"], session["end_time"]))
    m2.metric("Total Carp", session["total_catches"])
    m3.metric("Swims Fished", len({st["swim_name"] for st in stints}))

    mirror_count = session["mirror_count"] or 0
    common_count = session["common_count"] or 0
    st.caption(f"Variety Split: **{format_carp_ratio(mirror_count, common_count)}**")
    if session.get("notes"):
        st.caption(f"Session Notes: {session['notes']}")

    # --- 2. SWIM TIMELINE LEDGER ---
    st.subheader("Swim Timeline")
    for idx, stint in enumerate(stints, start=1):
        window = format_time_window(stint["started_at"], stint["ended_at"])
        dur = format_duration(stint["started_at"], stint["ended_at"])
        stint_catches = [
            c for c in catches
            if c["swim_stint_id"] == stint["id"] or (c["swim_stint_id"] is None and c["swim_name"] == stint["swim_name"])
        ]
        st.markdown(
            f"**{idx}. {stint['swim_name']}** — `{window}` ({dur}) • **{len(stint_catches)} carp**"
        )

    st.divider()

    # --- 3. SESSION CATCHES ---
    st.subheader("Session Catches")
    if not catches:
        st.info("No carp logged in this session yet.")
        return

    for c in catches:
        catch_time = datetime.fromisoformat(c["caught_at"]).strftime("%H:%M")
        moon_str = format_moon_label(c["moon_illumination_pct"], c["moon_phase"])
        with st.container(border=True):
            st.markdown(
                f"**{c['carp_type']} Carp** • **{format_weight(c['weight_grams'], primary_unit)}** "
                f"— **{c['rod']} Rod** (`{c['swim_name']}` @ `{catch_time}`)"
            )
            st.caption(f"Moon: {moon_str}")
            if c.get("description"):
                st.write(f"Fish: {c['description']}")
            if c.get("notes"):
                st.caption(f"Notes: {c['notes']}")