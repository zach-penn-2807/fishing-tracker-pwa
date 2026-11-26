from datetime import datetime
import streamlit as st

from src.database.db import (
    get_known_lakes,
    get_swims_for_lake,
    query_catches,
    summarize_catches,
)
from src.ui.formatting import (
    format_carp_ratio,
    format_weight,
    kg_to_grams,
    lb_oz_to_grams,
)
from src.utils.moon import MOON_PHASES, format_moon_label


def _render_summary_card(title: str, catches: list[dict], primary_unit: str) -> None:
    """Render a reusable summary block for a filtered set or comparison side."""
    stats = summarize_catches(catches)
    with st.container(border=True):
        st.markdown(f"**{title}**")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Carp", stats["total"])
        c2.metric("Biggest", format_weight(stats["max_grams"], primary_unit, show_secondary=False) if stats["max_grams"] else "—")
        c3.metric("Average", format_weight(stats["avg_grams"], primary_unit, show_secondary=False) if stats["avg_grams"] else "—")

        st.caption(f"Ratio: **{format_carp_ratio(stats['mirrors'], stats['commons'])}**")
        rod_bits = [
            f"{rod}: {info['total']} ({info['mirrors']}M/{info['commons']}C)"
            for rod, info in stats["rods"].items()
        ]
        st.caption("Rods — " + " • ".join(rod_bits))


def render_analytics_tab(primary_unit: str = "lb") -> None:
    """Render Tab 3: Lake -> Swim drill-down, compound filters, and A vs B comparisons."""
    all_catches = query_catches()
    if not all_catches:
        st.info("No carp catches logged yet. Log catches in Tab 1 to unlock drill-downs, filters, and comparisons.")
        return

    # --- 1. LAKE -> SWIM DRILL-DOWN & ROD SUMMARY ---
    st.subheader("Lake → Swim Drill-Down & Rod Summary")
    lakes = get_known_lakes()
    selected_lake = st.selectbox("Select Lake", options=lakes, key="drill_lake_select")

    lake_catches = query_catches(lake_name=selected_lake)
    _render_summary_card(f"{selected_lake} (All Swims)", lake_catches, primary_unit)

    swims_in_lake = get_swims_for_lake(selected_lake)
    if swims_in_lake:
        st.markdown("**Swims Fished on This Lake:**")
        for swim in swims_in_lake:
            swim_catches = query_catches(lake_name=selected_lake, swim_name=swim)
            swim_stats = summarize_catches(swim_catches)
            pb_str = (
                format_weight(swim_stats["max_grams"], primary_unit, show_secondary=False)
                if swim_stats["max_grams"]
                else "No catches"
            )
            st.markdown(
                f"- **{swim}** — {format_carp_ratio(swim_stats['mirrors'], swim_stats['commons'])} • PB: **{pb_str}**"
            )

    st.divider()

    # --- 2. COMPOUND FILTER & SIZE THRESHOLDS (> X / < Y) ---
    st.subheader("Catch Filter & Size Thresholds")
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        f_lake = st.selectbox("Filter Lake", options=["All Lakes"] + lakes, key="filter_lake")
        f_variety = st.selectbox("Carp Variety", options=["All", "Mirror", "Common"], key="filter_variety")
        f_moon = st.selectbox("Moon Phase", options=["All Phases"] + MOON_PHASES, key="filter_moon")
    with f_col2:
        swim_pool = get_swims_for_lake(None if f_lake == "All Lakes" else f_lake)
        f_swim = st.selectbox("Filter Swim", options=["All Swims"] + swim_pool, key="filter_swim")
        f_rod = st.selectbox("Rod", options=["All Rods", "Left", "Middle", "Right"], key="filter_rod")

    use_min = st.checkbox("Minimum weight filter (> X)", value=False, key="use_min_weight")
    min_grams: int | None = None
    if use_min:
        if primary_unit == "lb":
            m_lb, m_oz = st.columns(2)
            min_lb = m_lb.number_input("Min lb (>)", min_value=0, max_value=100, value=6, step=1, key="min_lb")
            min_oz = m_oz.number_input("Min oz (>)", min_value=0, max_value=15, value=5, step=1, key="min_oz")
            min_grams = lb_oz_to_grams(int(min_lb), int(min_oz))
        else:
            min_kg = st.number_input("Min weight > (kg)", min_value=0.0, max_value=50.0, value=3.0, step=0.1, key="min_kg")
            min_grams = kg_to_grams(float(min_kg))

    use_max = st.checkbox("Maximum weight filter (< Y)", value=False, key="use_max_weight")
    max_grams: int | None = None
    if use_max:
        if primary_unit == "lb":
            x_lb, x_oz = st.columns(2)
            max_lb = x_lb.number_input("Max lb (<)", min_value=0, max_value=100, value=20, step=1, key="max_lb")
            max_oz = x_oz.number_input("Max oz (<)", min_value=0, max_value=15, value=0, step=1, key="max_oz")
            max_grams = lb_oz_to_grams(int(max_lb), int(max_oz))
        else:
            max_kg = st.number_input("Max weight < (kg)", min_value=0.1, max_value=50.0, value=10.0, step=0.1, key="max_kg")
            max_grams = kg_to_grams(float(max_kg))

    matched = query_catches(
        lake_name=None if f_lake == "All Lakes" else f_lake,
        swim_name=None if f_swim == "All Swims" else f_swim,
        carp_type=None if f_variety == "All" else f_variety,
        rod=None if f_rod == "All Rods" else f_rod,
        moon_phase=None if f_moon == "All Phases" else f_moon,
        min_grams=min_grams,
        max_grams=max_grams,
    )
    _render_summary_card(f"Matching Catches ({len(matched)})", matched, primary_unit)

    for c in matched:
        ts_fmt = datetime.fromisoformat(c["caught_at"]).strftime("%d %b %H:%M")
        st.markdown(
            f"- **{c['carp_type']}** • **{format_weight(c['weight_grams'], primary_unit)}** • "
            f"**{c['rod']}** @ *{c['lake_name']} — {c['swim_name']}* ({ts_fmt}, {format_moon_label(c['moon_illumination_pct'], c['moon_phase'])})"
        )
        if c.get("description") or c.get("notes"):
            st.caption(f"{c.get('description') or ''} {'• ' + c['notes'] if c.get('notes') else ''}".strip(" •"))

    st.divider()

    # --- 3. SIDE-BY-SIDE COMPARISONS (A VS B) ---
    st.subheader("Compare A vs. B")
    compare_mode = st.radio(
        "Comparison Type",
        options=["Swim X vs. Swim Y", "Moon Phase X vs. Moon Phase Y"],
        horizontal=True,
        key="compare_mode",
    )

    if compare_mode == "Swim X vs. Swim Y":
        all_swims = get_swims_for_lake(None)
        if len(all_swims) < 2:
            st.info("Log catches across at least two swims to compare Swim X vs. Swim Y.")
        else:
            a_col, b_col = st.columns(2)
            swim_a = a_col.selectbox("Swim A", options=all_swims, index=0, key="cmp_swim_a")
            swim_b = b_col.selectbox(
                "Swim B",
                options=all_swims,
                index=1 if len(all_swims) > 1 else 0,
                key="cmp_swim_b",
            )
            _render_summary_card(f"Swim A: {swim_a}", query_catches(swim_name=swim_a), primary_unit)
            _render_summary_card(f"Swim B: {swim_b}", query_catches(swim_name=swim_b), primary_unit)
    else:
        m_col1, m_col2 = st.columns(2)
        moon_a = m_col1.selectbox("Moon Phase A", options=MOON_PHASES, index=0, key="cmp_moon_a")
        moon_b = m_col2.selectbox("Moon Phase B", options=MOON_PHASES, index=4, key="cmp_moon_b")
        _render_summary_card(f"Moon A: {moon_a}", query_catches(moon_phase=moon_a), primary_unit)
        _render_summary_card(f"Moon B: {moon_b}", query_catches(moon_phase=moon_b), primary_unit)