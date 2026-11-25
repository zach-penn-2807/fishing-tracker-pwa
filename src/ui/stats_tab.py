import plotly.express as px
import streamlit as st

from src.database.db import get_all_catches, get_trip_stats
from src.ui.formatting import format_timestamp, grams_to_lb_oz


def render_stats_tab() -> None:
    """Render overall catch visualisations and individual trip breakdowns."""
    catches = get_all_catches()
    trips = get_trip_stats()

    if not catches:
        st.info("No catches logged yet. Once your dad logs a catch, his stats and charts will appear here!")
        return

    # 1. Overall Career KPIs
    heaviest_fish = max(catches, key=lambda c: c["weight_grams"])
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Fish", len(catches))
    k2.metric("All-Time PB", grams_to_lb_oz(heaviest_fish["weight_grams"]).split(" (")[0])
    k3.metric("Total Trips", len(trips))

    st.divider()

    # 2. Catch Count & Size Charts
    species_counts: dict[str, int] = {}
    for c in catches:
        species_counts[c["species"]] = species_counts.get(c["species"], 0) + 1

    fig_count = px.bar(
        x=list(species_counts.keys()),
        y=list(species_counts.values()),
        labels={"x": "Species", "y": "Fish Caught"},
        title="Total Fish Caught by Species",
    )
    fig_count.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig_count, use_container_width=True, config={"displayModeBar": False})

    chart_rows = [
        {
            "Species": c["species"],
            "Weight (lb)": round(c["weight_grams"] / 453.59237, 2),
            "Spot": c["spot_name"],
            "Date": format_timestamp(c["caught_at"]),
        }
        for c in catches
    ]
    fig_sizes = px.box(
        chart_rows,
        x="Species",
        y="Weight (lb)",
        points="all",
        hover_data=["Spot", "Date"],
        title="Fish Size Distribution & Personal Bests (lb)",
    )
    fig_sizes.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig_sizes, use_container_width=True, config={"displayModeBar": False})

    st.divider()

    # 3. Individual Trip Inspector (Single Session or Multi-Day)
    st.subheader("🗓️ Individual Trip Stats")
    trip_lookup = {f"{t['trip_name']} ({format_timestamp(t['start_time'])})": t for t in trips}
    selected_label = st.selectbox("Select Trip", list(trip_lookup.keys()))
    selected_trip = trip_lookup[selected_label]
    trip_catches = [c for c in catches if c["trip_id"] == selected_trip["id"]]

    t1, t2 = st.columns(2)
    t1.metric("Trip Total", f"{selected_trip['total_fish']} fish")
    t2.metric(
        "Trip Best",
        grams_to_lb_oz(selected_trip["max_weight_grams"]).split(" (")[0]
        if selected_trip["max_weight_grams"] > 0
        else "—",
    )

    if trip_catches:
        for c in trip_catches:
            st.markdown(
                f"- **{c['species']}** — {grams_to_lb_oz(c['weight_grams'])} "
                f"at *{c['spot_name']}* ({format_timestamp(c['caught_at'])})"
            )
    else:
        st.caption("No fish logged on this trip yet.")