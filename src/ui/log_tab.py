import streamlit as st
from streamlit_js_eval import get_geolocation

from src.database.db import get_active_trip, log_catch, start_trip
from src.ui.formatting import format_timestamp, grams_to_lb_oz, kg_to_grams, lb_oz_to_grams

COMMON_SPECIES = ["Carp", "Pike", "Perch", "Bream", "Roach", "Tench", "Chub", "Barbel", "Other"]


def _capture_gps() -> tuple[float | None, float | None]:
    """Request live GPS coordinates from Safari/browser without blocking the UI."""
    loc = get_geolocation()
    if isinstance(loc, dict) and "coords" in loc:
        coords = loc["coords"]
        return coords.get("latitude"), coords.get("longitude")
    return None, None


def render_log_tab() -> None:
    """Render the streamlined mobile catch-logging screen."""
    active_trip = get_active_trip()

    # 1. Trip Management Header
    if not active_trip:
        st.info("No active fishing trip. Start a session or multi-day trip below to begin logging.")
        with st.form("start_trip_form"):
            trip_name = st.text_input("Trip / Session Name", placeholder="e.g., Morning Session - Willow Lake")
            notes = st.text_input("Notes (optional)", placeholder="Weather, swim/peg, bait...")
            if st.form_submit_button("Start Fishing Trip", type="primary", use_container_width=True):
                if trip_name.strip():
                    start_trip(trip_name)
                    st.rerun()
                else:
                    st.warning("Please enter a trip name first.")
        return

    # Active Trip Banner + Quick Switch/End Trip option
    st.success(f"**Active Trip:** {active_trip['name']} (Started {format_timestamp(active_trip['start_time'])})")
    with st.expander("Switch or Start a New Trip"):
        new_trip_name = st.text_input("New Trip Name", key="switch_trip_name")
        if st.button("Close Current & Start New Trip", use_container_width=True):
            if new_trip_name.strip():
                start_trip(new_trip_name)
                st.rerun()

    st.divider()

    # 2. Automatic GPS Capture
    lat, lon = _capture_gps()
    if lat is not None and lon is not None:
        st.caption(f"GPS Locked: `{lat:.5f}, {lon:.5f}` (auto-snaps to spots within 200m)")
    else:
        st.caption("Waiting for GPS signal... (or enter coordinates manually below for testing)")

    with st.expander("Location / Spot Name (Optional)"):
        spot_name = st.text_input("New Spot / Lake Name", placeholder="Auto-matches saved spots within 200m")
        col_lat, col_lon = st.columns(2)
        manual_lat = col_lat.number_input("Manual Lat", value=lat or 0.0, format="%.5f")
        manual_lon = col_lon.number_input("Manual Lon", value=lon or 0.0, format="%.5f")
        final_lat = lat if lat is not None else (manual_lat if manual_lat != 0.0 else None)
        final_lon = lon if lon is not None else (manual_lon if manual_lon != 0.0 else None)

    # 3. Species & Weight Inputs (Large Touch Targets)
    species = st.pills("Species", COMMON_SPECIES, default="Carp")
    if species == "Other" or species is None:
        species = st.text_input("Enter Species Name", placeholder="e.g., Grayling")

    unit = st.radio("Weight Unit", ["lb / oz", "kg"], horizontal=True)
    if unit == "lb / oz":
        c1, c2 = st.columns(2)
        lbs = c1.number_input("Pounds (lb)", min_value=0, max_value=150, value=5, step=1)
        oz = c2.number_input("Ounces (oz)", min_value=0.0, max_value=15.9, value=0.0, step=0.5)
        weight_grams = lb_oz_to_grams(int(lbs), float(oz))
    else:
        kg = st.number_input("Weight (kg)", min_value=0.01, max_value=70.0, value=2.50, step=0.05)
        weight_grams = kg_to_grams(float(kg))

    st.write("")
    if st.button("LOG CATCH", type="primary", use_container_width=True):
        if not species or not species.strip():
            st.error("Please select or enter a fish species.")
            return
        log_catch(
            trip_id=active_trip["id"],
            species=species,
            weight_grams=weight_grams,
            lat=final_lat,
            lon=final_lon,
            spot_name=spot_name,
        )
        st.toast(f"Logged {species} — {grams_to_lb_oz(weight_grams)}!", icon="🎣")
        st.balloons()