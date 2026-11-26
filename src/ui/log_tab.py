from datetime import datetime, time
import streamlit as st

from src.database.db import (
    end_session,
    find_stint_for_timestamp,
    get_active_session,
    get_known_lakes,
    get_session_stints,
    get_swims_for_lake,
    log_catch,
    start_session,
    switch_swim,
)
from src.ui.formatting import (
    format_duration,
    format_time_window,
    kg_to_grams,
    lb_oz_to_grams,
)
from src.utils.moon import calculate_moon_details, format_moon_label


def _combine_today_time(picked_time: time) -> str:
    """Combine today's date with a selected HH:MM time into an ISO minute string."""
    now = datetime.now()
    combined = datetime.combine(now.date(), picked_time)
    return combined.isoformat(timespec="minutes")


def render_log_tab() -> None:
    """Render Tab 1: Active session controls, swim switcher, and carp catch logger."""
    active_session = get_active_session()

    # --- 1. NO ACTIVE SESSION: START SESSION CARD ---
    if not active_session:
        st.subheader("Start Fishing Session")
        known_lakes = get_known_lakes()
        lake_choice = st.selectbox(
            "Select Lake",
            options=["+ New Lake..."] + known_lakes,
            index=1 if known_lakes else 0,
        )
        lake_name = (
            st.text_input("New Lake Name", placeholder="e.g. Bluebell Swan Lake")
            if lake_choice == "+ New Lake..."
            else lake_choice
        )

        known_swims = get_swims_for_lake(lake_name) if lake_name else []
        swim_choice = st.selectbox(
            "Starting Swim",
            options=["+ New Swim..."] + known_swims,
            index=1 if known_swims else 0,
        )
        starting_swim = (
            st.text_input("Starting Swim Name", placeholder="e.g. Swim 4 / The Point")
            if swim_choice == "+ New Swim..."
            else swim_choice
        )

        start_t = st.time_input(
            "Session Start Time",
            value=datetime.now().time().replace(second=0, microsecond=0),
        )
        session_notes = st.text_input(
            "Session Notes (optional)",
            placeholder="Weather, wind direction, water temp...",
        )

        if st.button("START SESSION", type="primary", use_container_width=True):
            if not lake_name.strip() or not starting_swim.strip():
                st.error("Please enter both a Lake name and a Starting Swim.")
            else:
                start_session(
                    lake_name=lake_name,
                    starting_swim=starting_swim,
                    start_time=_combine_today_time(start_t),
                    notes=session_notes,
                )
                st.rerun()
        return

    # --- 2. ACTIVE SESSION HEADER & SWIM SWITCHER ---
    session_id = active_session["id"]
    lake_name = active_session["lake_name"]
    active_stint = active_session.get("active_stint")
    current_swim = active_stint["swim_name"] if active_stint else "Unknown Swim"
    session_stints = get_session_stints(session_id)

    st.success(
        f"**{lake_name}** • Active Swim: **{current_swim}** "
        f"(Session: {format_duration(active_session['start_time'])})"
    )

    with st.expander("Switch Swim / End Session", expanded=False):
        st.caption(
            f"Currently in **{current_swim}** since "
            f"{datetime.fromisoformat(active_stint['started_at']).strftime('%H:%M') if active_stint else '--:--'}"
        )
        lake_swims = [s for s in get_swims_for_lake(lake_name) if s != current_swim]
        next_swim_choice = st.selectbox(
            "Move to Swim",
            options=["+ New Swim..."] + lake_swims,
            key="switch_swim_select",
        )
        next_swim = (
            st.text_input("New Swim Name", placeholder="e.g. Swim 7", key="switch_swim_text")
            if next_swim_choice == "+ New Swim..."
            else next_swim_choice
        )
        switch_t = st.time_input(
            "Time Switched (defaults to now)",
            value=datetime.now().time().replace(second=0, microsecond=0),
            key="switch_time_input",
        )

        col_sw, col_end = st.columns(2)
        with col_sw:
            if st.button("SWITCH SWIM", use_container_width=True):
                if not next_swim.strip():
                    st.error("Enter a swim name to switch to.")
                else:
                    try:
                        switch_swim(
                            session_id=session_id,
                            new_swim_name=next_swim,
                            switched_at=_combine_today_time(switch_t),
                        )
                        st.rerun()
                    except ValueError as err:
                        st.error(str(err))
        with col_end:
            if st.button("END SESSION", type="secondary", use_container_width=True):
                end_session(session_id)
                st.rerun()

    st.divider()

    # --- 3. RETROACTIVE SWIM STINT PROMPT (IF TRIGGERED) ---
    pending = st.session_state.get("pending_catch_mismatch")
    if pending:
        matched_stint = pending["matched_stint"]
        window_str = format_time_window(matched_stint["started_at"], matched_stint["ended_at"])
        st.warning(
            f"Catch time **{pending['caught_at'][-5:]}** falls inside an earlier swim stint: "
            f"**{matched_stint['swim_name']}** ({window_str}). Should this catch be logged under "
            f"**{matched_stint['swim_name']}** instead of **{pending['chosen_swim']}**?"
        )
        c_yes, c_no = st.columns(2)
        with c_yes:
            if st.button(f"Yes — Log in {matched_stint['swim_name']}", type="primary", use_container_width=True):
                payload = pending["payload"]
                payload["swim_name"] = matched_stint["swim_name"]
                payload["swim_stint_id"] = matched_stint["id"]
                log_catch(**payload)
                del st.session_state["pending_catch_mismatch"]
                st.toast("Catch saved under earlier swim!")
                st.rerun()
        with c_no:
            if st.button(f"No — Keep {pending['chosen_swim']}", use_container_width=True):
                payload = pending["payload"]
                log_catch(**payload)
                del st.session_state["pending_catch_mismatch"]
                st.toast("Catch saved!")
                st.rerun()
        return

    # --- 4. CARP CATCH ENTRY FORM ---
    st.subheader("Log Carp Catch")

    carp_type = st.segmented_control(
        "Carp Type",
        options=["Mirror", "Common"],
        default="Mirror",
    )
    rod = st.segmented_control(
        "Rod",
        options=["Left", "Middle", "Right"],
        default="Middle",
    )

    unit_toggle = st.radio(
        "Weight Unit",
        options=["lb", "kg"],
        format_func=lambda u: "UK lb / oz" if u == "lb" else "Kilograms (kg)",
        horizontal=True,
    )

    if unit_toggle == "lb":
        w_col1, w_col2 = st.columns(2)
        with w_col1:
            lbs = st.number_input("Pounds (lb)", min_value=0, max_value=100, value=12, step=1)
        with w_col2:
            oz = st.number_input("Ounces (oz)", min_value=0, max_value=15, value=0, step=1)
        weight_grams = lb_oz_to_grams(int(lbs), int(oz))
    else:
        kg_val = st.number_input("Weight (kg)", min_value=0.1, max_value=50.0, value=5.50, step=0.05)
        weight_grams = kg_to_grams(float(kg_val))

    # Swim selector (defaults to active swim, allows switching to any session/lake swim)
    session_swim_names = list(dict.fromkeys([s["swim_name"] for s in session_stints] + get_swims_for_lake(lake_name)))
    default_idx = session_swim_names.index(current_swim) if current_swim in session_swim_names else 0
    selected_swim = st.selectbox("Swim Caught In", options=session_swim_names, index=default_idx)

    catch_t = st.time_input(
        "Time of Catch",
        value=datetime.now().time().replace(second=0, microsecond=0),
    )
    caught_at_iso = _combine_today_time(catch_t)

    moon_info = calculate_moon_details(datetime.fromisoformat(caught_at_iso))
    st.caption(f"Moon Phase at Catch: **{format_moon_label(moon_info['illumination_pct'], moon_info['phase_name'])}**")

    description = st.text_input(
        "Fish Description",
        placeholder="e.g. Dark plated mirror, split tail, apple slice scales...",
    )
    notes = st.text_input(
        "Notes (Bait / Rig / Misc)",
        placeholder="e.g. 15mm Krill wafter over PVA mesh bag, Ronnie rig...",
    )

    if st.button("LOG CATCH", type="primary", use_container_width=True):
        if not carp_type or not rod:
            st.error("Please select both Carp Type (Mirror/Common) and Rod (Left/Middle/Right).")
            return
        if weight_grams <= 0:
            st.error("Weight must be greater than zero.")
            return

        # Determine stint ID for selected swim and check retroactive timestamp match
        stint_for_time = find_stint_for_timestamp(session_id, caught_at_iso)
        chosen_stint_id = (
            active_stint["id"]
            if (active_stint and selected_swim == active_stint["swim_name"])
            else None
        )

        payload = {
            "session_id": session_id,
            "lake_name": lake_name,
            "swim_name": selected_swim,
            "carp_type": carp_type,
            "rod": rod,
            "weight_grams": weight_grams,
            "caught_at": caught_at_iso,
            "swim_stint_id": chosen_stint_id,
            "moon_illumination_pct": moon_info["illumination_pct"],
            "moon_phase": moon_info["phase_name"],
            "description": description,
            "notes": notes,
        }

        if stint_for_time and stint_for_time["swim_name"] != selected_swim:
            st.session_state["pending_catch_mismatch"] = {
                "matched_stint": stint_for_time,
                "chosen_swim": selected_swim,
                "payload": payload,
            }
            st.rerun()

        log_catch(**payload)
        st.toast(f"Logged {carp_type} carp on {rod} rod!")
        st.rerun()