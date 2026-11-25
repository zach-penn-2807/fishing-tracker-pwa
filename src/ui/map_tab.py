import folium
import streamlit as st
from streamlit_folium import st_folium

from src.database.db import get_all_catches, get_spot_stats
from src.ui.formatting import format_timestamp, grams_to_lb_oz


def render_map_tab() -> None:
    """Render interactive catch map and per-venue/spot personal bests."""
    catches = get_all_catches()
    spots = get_spot_stats()

    if not catches:
        st.info("No catches logged yet. Log your first catch to see pins and lake stats here!")
        return

    # 1. Interactive Folium Map
    gps_catches = [c for c in catches if c["lat"] is not None and c["lon"] is not None]
    if gps_catches:
        avg_lat = sum(c["lat"] for c in gps_catches) / len(gps_catches)
        avg_lon = sum(c["lon"] for c in gps_catches) / len(gps_catches)

        catch_map = folium.Map(location=[avg_lat, avg_lon], zoom_start=14, control_scale=True)
        for c in gps_catches:
            popup_html = (
                f"<b>{c['species']}</b><br>"
                f"{grams_to_lb_oz(c['weight_grams'])}<br>"
                f"<i>{c['spot_name']}</i><br>"
                f"{format_timestamp(c['caught_at'])}"
            )
            folium.Marker(
                location=[c["lat"], c["lon"]],
                popup=folium.Popup(popup_html, max_width=220),
                tooltip=f"{c['species']} ({grams_to_lb_oz(c['weight_grams'])})",
                icon=folium.Icon(color="green", icon="info-sign"),
            ).add_to(catch_map)

        st_folium(catch_map, use_container_width=True, height=340, returned_objects=[])
    else:
        st.warning("Catches logged so far do not have GPS coordinates attached.")

    # 2. Per-Spot / Lake Leaderboard Cards
    st.subheader("📍 Stats by Spot / Lake")
    for spot in spots:
        if spot["total_fish"] == 0:
            continue
        with st.container(border=True):
            st.markdown(f"### {spot['spot_name']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Caught", spot["total_fish"])
            c2.metric("Biggest (PB)", grams_to_lb_oz(spot["max_weight_grams"]).split(" (")[0])
            c3.metric("Average", grams_to_lb_oz(int(spot["avg_weight_grams"])).split(" (")[0])