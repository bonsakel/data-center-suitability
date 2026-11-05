from pathlib import Path
from html import escape
from urllib.parse import urlparse

import pandas as pd
import pydeck as pdk
import streamlit as st


# Set the page title and layout before loading the project data.
st.set_page_config(page_title="The Geography of the AI Boom", layout="wide")
st.title("The Geography of the AI Boom")
st.caption("Mapping data center development and documented community opposition")


# Keep linked source URLs safe to display in the map tooltip.
def safe_link(value):
    source = str(value).strip()
    if urlparse(source).scheme in {"http", "https"}:
        return escape(source, quote=True)
    return ""


# Load precomputed tables so the app does not redo the analysis.
@st.cache_data
def load_data():
    project = Path(__file__).resolve().parents[1]
    clean = project / "data" / "clean"
    registry = pd.read_csv(clean / "registry_county_joined.csv")
    fights = pd.read_csv(clean / "opposition_county_joined.csv")
    counties = pd.read_csv(clean / "county_summary.csv", dtype={"GEOID": str})
    concerns = pd.read_csv(clean / "county_concern_counts.csv", dtype={"GEOID": str})
    nearest = pd.read_csv(clean / "proposed_nearest_operating.csv")
    summary = pd.read_csv(clean / "hub_frontier_summary.csv")
    return registry, fights, counties, concerns, nearest, summary


# Read all prepared tables once and stop clearly if setup has not been run.
registry, fights, counties, county_concerns, nearest, group_summary = load_data()
if fights.empty or counties.empty:
    st.error("Prepared data is missing. Run scripts 01 through 04 before starting the app.")
    st.stop()


# Explain the key limitation before users explore the records.
st.info(
    "These maps show documented patterns, not proof that data centers caused "
    "opposition. Records reflect monitoring and media coverage."
)
map_tab, county_tab, frontier_tab = st.tabs(
    ["Map", "Find your county", "Frontier explorer"]
)


# Show facilities, opposition points, filters, and one chart.
with map_tab:
    left, right = st.columns([3, 1])

    # Set filters from the values actually present in the cleaned records.
    concern_values = sorted(
        {
            item
            for value in fights["issue_category"].fillna("")
            for item in str(value).split("; ")
            if item
        }
    )
    outcome_values = sorted(fights["community_outcome"].dropna().unique())
    with right:
        concern_filter = st.selectbox("Concern", ["All concerns", *concern_values])
        outcome_filter = st.selectbox(
            "Tracker-coded outcome", ["All outcomes", *outcome_values]
        )
        map_mode = st.radio("Map view", ["2D points", "3D opposition hexagons"])
        if map_mode.startswith("3D"):
            st.caption("Hexagon height represents filtered record counts; height is not a physical value.")

    # Apply the selected filters to opposition records only.
    map_fights = fights.copy()
    if concern_filter != "All concerns":
        has_concern = map_fights["issue_category"].fillna("").str.split("; ").apply(
            lambda items: concern_filter in items
        )
        map_fights = map_fights.loc[has_concern].copy()
    if outcome_filter != "All outcomes":
        map_fights = map_fights.loc[
            map_fights["community_outcome"].eq(outcome_filter)
        ].copy()

    # Add a readable label and first source URL for map tooltips.
    map_fights["place"] = (
        map_fights["jurisdiction"].fillna("")
        + ", "
        + map_fights["state"].fillna("")
    )
    map_fights["tooltip_place"] = map_fights["place"].map(escape)
    map_fights["issue_category"] = map_fights["issue_category"].fillna("").map(escape)
    map_fights["community_outcome"] = map_fights["community_outcome"].fillna("").map(escape)
    map_fights["source_link"] = (
        map_fights["sources"].fillna("").str.split("; ").str[0].map(safe_link)
    )
    map_registry = registry.copy()
    map_registry["tooltip_place"] = (
        map_registry["name"].fillna("Unnamed facility")
        + ", "
        + map_registry["state"].fillna("")
    ).map(escape)
    map_registry["issue_category"] = ""
    map_registry["community_outcome"] = ""
    map_registry["source_link"] = map_registry["profile_url"].map(safe_link)
    facility_colors = {
        "operating": [35, 139, 112, 190],
        "proposed": [237, 170, 45, 190],
        "permitted": [210, 105, 30, 190],
        "under_construction": [65, 125, 190, 190],
        "cancelled": [120, 120, 120, 140],
    }
    map_registry["color"] = map_registry["status_clean"].map(facility_colors)

    # Create separate layers for the registry sites and filtered opposition.
    facility_layer = pdk.Layer(
        "ScatterplotLayer",
        data=map_registry,
        get_position="[longitude, latitude]",
        get_fill_color="color",
        get_radius=2200,
        pickable=True,
        auto_highlight=True,
    )
    if map_mode == "3D opposition hexagons":
        opposition_layer = pdk.Layer(
            "HexagonLayer",
            data=map_fights,
            get_position="[lng, lat]",
            radius=10000,
            elevation_scale=20,
            get_elevation_weight=1,
            elevation_aggregation="SUM",
            extruded=True,
            pickable=True,
        )
    else:
        opposition_layer = pdk.Layer(
            "ScatterplotLayer",
            data=map_fights,
            get_position="[lng, lat]",
            get_fill_color=[205, 55, 60, 170],
            get_radius=3500,
            pickable=True,
            auto_highlight=True,
        )

    # Draw the selected layers and a side chart that follows the filters.
    view = pdk.ViewState(latitude=39, longitude=-98, zoom=3.1, pitch=35 if map_mode.startswith("3D") else 0)
    deck = pdk.Deck(
        layers=[facility_layer, opposition_layer],
        initial_view_state=view,
        tooltip={
            "html": "<b>{tooltip_place}</b><br/>Status: {status_clean}<br/>Concern: {issue_category}<br/>Outcome: {community_outcome}<br/><a href='{source_link}' target='_blank' rel='noopener noreferrer'>Source</a>",
            "style": {"backgroundColor": "#1f2937", "color": "white"},
        },
        map_style=None,
    )
    with left:
        st.pydeck_chart(deck, width="stretch")
    with right:
        st.metric("Filtered opposition records", f"{len(map_fights):,}")
        chart = (
            map_fights["issue_category"]
            .fillna("")
            .str.split("; ")
            .explode()
            .loc[lambda values: values.ne("")]
            .value_counts()
            .head(10)
        )
        st.caption("Concern tags in the filtered records")
        st.bar_chart(chart)

    # Let users open one filtered record and follow its source links.
    if not map_fights.empty:
        record_ids = map_fights["id"].astype(str).tolist()
        selected_id = st.selectbox("Open a record", record_ids)
        record = map_fights.loc[map_fights["id"].astype(str).eq(selected_id)].iloc[0]
        st.subheader(record["jurisdiction"])
        st.write(record["summary"])
        groups = record.get("opposition_groups")
        signatures = record.get("petition_signatures")
        st.write("Organized groups:", groups if pd.notna(groups) and groups else "Not listed")
        st.write(
            "Petition signatures:",
            signatures if pd.notna(signatures) else "Not listed",
        )
        for number, source in enumerate(str(record.get("sources", "")).split("; "), 1):
            if urlparse(source).scheme in {"http", "https"}:
                st.link_button(f"Source {number}", source)
    else:
        st.info("No opposition records match these filters.")


# Search for either a county or a state and show precomputed counts.
with county_tab:
    query = st.text_input("Enter a county, state name, or state abbreviation")
    if query.strip():
        search = query.strip().casefold()
        state_match = counties.loc[
            counties["STUSPS"].str.casefold().eq(search)
            | counties["STATE_NAME"].str.casefold().eq(search)
        ]

        # Aggregate counties when the search is an exact state name or code.
        if not state_match.empty:
            row = state_match.iloc[0]
            st.subheader(row["STATE_NAME"])
            facility_columns = [
                "operating_count",
                "proposed_count",
                "permitted_count",
                "under_construction_count",
                "cancelled_count",
            ]
            total = state_match[facility_columns + ["planned_count", "opposition_records"]].sum()
            st.write("Facilities by status:", total[facility_columns].to_dict())
            st.metric("Opposition records", f"{int(total['opposition_records']):,}")
            st.metric("Planned facilities", f"{int(total['planned_count']):,}")
            if total["planned_count"] > 0:
                st.metric(
                    "Records per planned facility",
                    f"{total['opposition_records'] / total['planned_count']:.3f}",
                )
            else:
                st.write("Opposition rate: not defined; there are no planned facilities.")
            state_concerns = county_concerns.merge(
                state_match[["GEOID", "STUSPS"]], on="GEOID", how="inner"
            )
            if not state_concerns.empty:
                st.write(
                    "Top concern:",
                    state_concerns.groupby("issue_category")["count"]
                    .sum()
                    .idxmax(),
                )
            if total["opposition_records"] == 0 and total[facility_columns].sum() == 0:
                st.info("No facility or opposition records are mapped to this state.")
        else:
            # Show matching counties so duplicate county names can be distinguished.
            matches = counties.loc[
                counties["NAME"].str.casefold().str.contains(search, regex=False)
            ].copy()
            if matches.empty:
                st.info("No county or state matched that search.")
            else:
                matches["label"] = matches["NAME"] + ", " + matches["STUSPS"]
                selected_label = st.selectbox("Choose a county", matches["label"].tolist())
                row = matches.loc[matches["label"].eq(selected_label)].iloc[0]
                st.subheader(f"{row['NAME']} County, {row['STUSPS']}")
                st.write(
                    "Facilities by status:",
                    {
                        "operating": int(row["operating_count"]),
                        "proposed": int(row["proposed_count"]),
                        "permitted": int(row["permitted_count"]),
                        "under construction": int(row["under_construction_count"]),
                        "cancelled": int(row["cancelled_count"]),
                    },
                )
                st.metric("Opposition records", f"{int(row['opposition_records']):,}")
                if row["planned_count"] > 0:
                    st.metric(
                        "Records per planned facility",
                        f"{row['opposition_per_planned_facility']:.3f}",
                    )
                else:
                    st.write("Opposition rate: not defined; there are no planned facilities.")
                top_concern = row["top_concern"]
                st.write(
                    "Top concern:",
                    top_concern if pd.notna(top_concern) else "No concern records",
                )
                if row["opposition_records"] == 0 and row["planned_count"] == 0:
                    st.info("No facility or opposition records are mapped to this county.")


# Explore precomputed geodesic distance from proposed sites to operating sites.
with frontier_tab:
    st.caption(
        "Distances use WGS 84 geodesic measurements. Compare them with ArcGIS Near "
        "using the Geodesic method."
    )
    nearest["label"] = nearest["proposed_name"].fillna(nearest["proposed_id"]) + " (" + nearest[
        "state"
    ] + ")"
    selected_label = st.selectbox("Choose a proposed facility", nearest["label"].tolist())
    site = nearest.loc[nearest["label"].eq(selected_label)].iloc[0]
    st.metric("Distance to nearest operating site", f"{site['distance_km']:.1f} km")
    st.write(
        f"Nearest operating site: {site['nearest_operating_name']} "
        f"({site['distance_miles']:.1f} miles)"
    )

    # Draw the selected proposed site, operating site, and connecting line.
    path = [
        [
            [site["proposed_longitude"], site["proposed_latitude"]],
            [site["operating_longitude"], site["operating_latitude"]],
        ]
    ]
    line_layer = pdk.Layer(
        "PathLayer",
        data=[{"path": path[0]}],
        get_path="path",
        get_width=4,
        get_color=[45, 110, 190],
        width_min_pixels=3,
    )
    point_data = pd.DataFrame(
        [
            {
                "longitude": site["proposed_longitude"],
                "latitude": site["proposed_latitude"],
                "place": site["proposed_name"],
            },
            {
                "longitude": site["operating_longitude"],
                "latitude": site["operating_latitude"],
                "place": site["nearest_operating_name"],
            },
        ]
    )
    point_layer = pdk.Layer(
        "ScatterplotLayer",
        data=point_data,
        get_position="[longitude, latitude]",
        get_fill_color=[205, 55, 60, 200],
        get_radius=5000,
        pickable=True,
    )
    view = pdk.ViewState(
        latitude=(site["proposed_latitude"] + site["operating_latitude"]) / 2,
        longitude=(site["proposed_longitude"] + site["operating_longitude"]) / 2,
        zoom=5,
    )
    st.pydeck_chart(
        pdk.Deck(
            layers=[line_layer, point_layer],
            initial_view_state=view,
            tooltip={"text": "{place}"},
            map_style=None,
        ),
        width="stretch",
    )
