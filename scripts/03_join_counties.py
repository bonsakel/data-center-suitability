from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Geod


# Print row counts so each join and filter is easy to explain.
def print_counts(step, before, after, reason):
    print(
        f"{step}: before={before:,}, after={after:,}, "
        f"dropped={before - after:,} ({reason})"
    )


# Find all source and output files from the project root.
project = Path(__file__).resolve().parents[1]
clean = project / "data" / "clean"
raw = project / "data" / "raw"
county_path = raw / "census" / "cb_2025_us_county_500k.zip"
population_path = raw / "census" / "co-est2025-alldata.csv"

# Keep the 50 states using their Census state FIPS codes.
state_fips = {
    "01", "02", "04", "05", "06", "08", "09", "10", "12", "13",
    "15", "16", "17", "18", "19", "20", "21", "22", "23", "24",
    "25", "26", "27", "28", "29", "30", "31", "32", "33", "34",
    "35", "36", "37", "38", "39", "40", "41", "42", "44", "45",
    "46", "47", "48", "49", "50", "51", "53", "54", "55", "56",
}

# Read the Census boundaries and keep counties in the 50 states.
counties = gpd.read_file(f"zip://{county_path}")
before = len(counties)
counties = counties.loc[counties["STATEFP"].isin(state_fips)].copy()
print_counts("Keep 50-state counties", before, len(counties), "DC and territory boundaries excluded")

# Load July 2025 estimates, which use Latin-1 text, and build county GEOIDs.
population = pd.read_csv(
    population_path, dtype={"STATE": str, "COUNTY": str}, encoding="latin-1"
)
before = len(population)
population = population.loc[
    population["SUMLEV"].eq(50) & population["STATE"].isin(state_fips)
].copy()
population["GEOID"] = population["STATE"] + population["COUNTY"]
population = population[["GEOID", "POPESTIMATE2025"]].rename(
    columns={"POPESTIMATE2025": "population_2025"}
)
print_counts("Keep 50-state county population", before, len(population), "state totals, DC, and territories excluded")

# Add population to each county using the Census county GEOID.
before = len(counties)
counties = counties.merge(population, on="GEOID", how="left", validate="one_to_one")
print_counts("Join county population", before, len(counties), "left join; unmatched counties retained")
print(f"Counties without population: {counties['population_2025'].isna().sum():,}")
counties = counties.set_index("GEOID")
county_shapes = counties.reset_index()[["GEOID", "geometry"]]

# Build a county-project key so repeated actions for one named project count together.
fights = pd.read_csv(clean / "opposition_local_clean.csv")
fights["project_label"] = fights["project_name"].fillna("").astype(str).str.strip()
company_label = fights["company"].fillna("").astype(str).str.strip()
fights["project_label"] = fights["project_label"].where(
    fights["project_label"].ne(""), company_label
)
fights["fight_key"] = fights["project_label"].where(
    fights["project_label"].ne(""), fights["id"].astype(str)
)

# Read cleaned facility and opposition records as point layers.
registry = pd.read_csv(clean / "registry_clean.csv")
registry_points = gpd.GeoDataFrame(
    registry,
    geometry=gpd.points_from_xy(registry["longitude"], registry["latitude"]),
    crs="EPSG:4326",
).to_crs(counties.crs)
fight_points = gpd.GeoDataFrame(
    fights,
    geometry=gpd.points_from_xy(fights["lng"], fights["lat"]),
    crs="EPSG:4326",
).to_crs(counties.crs)

# Assign facility points to their containing county.
registry_joined = gpd.sjoin(
    registry_points, county_shapes, how="left", predicate="within"
)
print(f"Facilities without a county: {registry_joined['GEOID'].isna().sum():,}")

# Assign opposition points to their containing county.
fight_joined = gpd.sjoin(
    fight_points, county_shapes, how="left", predicate="within"
)
print(f"Opposition records without a county: {fight_joined['GEOID'].isna().sum():,}")

# Find the nearest operating facility to each proposed site using geodesic distance.
operating = registry.loc[registry["status_clean"].eq("operating")].reset_index(drop=True)
proposed = registry.loc[registry["status_clean"].eq("proposed")]
geod = Geod(ellps="WGS84")
nearest_sites = []
for site in proposed.itertuples(index=False):
    distances = geod.inv(
        [site.longitude] * len(operating),
        [site.latitude] * len(operating),
        operating["longitude"].tolist(),
        operating["latitude"].tolist(),
    )[2]
    nearest_index = min(range(len(distances)), key=distances.__getitem__)
    nearest = operating.iloc[nearest_index]
    nearest_sites.append(
        {
            "proposed_id": site.id,
            "proposed_name": site.name,
            "state": site.state,
            "proposed_latitude": site.latitude,
            "proposed_longitude": site.longitude,
            "nearest_operating_id": nearest["id"],
            "nearest_operating_name": nearest["name"],
            "operating_latitude": nearest["latitude"],
            "operating_longitude": nearest["longitude"],
            "distance_km": distances[nearest_index] / 1000,
            "distance_miles": distances[nearest_index] / 1609.344,
        }
    )
nearest_sites = pd.DataFrame(nearest_sites)
print(f"Proposed sites with a nearest operating site: {len(nearest_sites):,}")

# Count facilities by status for every county.
status_counts = registry_joined.groupby(["GEOID", "status_clean"]).size().unstack(fill_value=0)
status_counts = status_counts.rename(
    columns={
        "operating": "operating_count",
        "proposed": "proposed_count",
        "permitted": "permitted_count",
        "under_construction": "under_construction_count",
        "cancelled": "cancelled_count",
        "other": "other_status_count",
    }
)

# Count opposition records and distinct county-project groups.
opposition_counts = fight_joined.groupby("GEOID").agg(
    opposition_records=("id", "size"),
    opposition_fights=("fight_key", "nunique"),
)
project_counts = (
    fight_joined.loc[fight_joined["fight_type"].eq("project_specific_fight")]
    .groupby("GEOID")["fight_key"]
    .nunique()
    .rename("project_fights")
)

# Count concerns by county and choose the most common concern.
concerns = fight_joined[["GEOID", "issue_category"]].copy()
concerns["issue_category"] = concerns["issue_category"].fillna("").str.split("; ")
concerns = concerns.explode("issue_category")
concerns = concerns.loc[concerns["issue_category"].ne("")]
concern_counts = concerns.groupby(["GEOID", "issue_category"]).size().rename("count").reset_index()
top_concerns = concern_counts.sort_values(
    ["GEOID", "count", "issue_category"], ascending=[True, False, True]
).drop_duplicates("GEOID")
top_concerns = top_concerns.set_index("GEOID")[["issue_category"]].rename(
    columns={"issue_category": "top_concern"}
)

# Combine counts, keep empty counties, and calculate the planned-facility rate.
county_summary = counties.join(status_counts).join(opposition_counts).join(project_counts).join(top_concerns)
count_columns = [
    "operating_count",
    "proposed_count",
    "permitted_count",
    "under_construction_count",
    "cancelled_count",
    "other_status_count",
    "opposition_records",
    "opposition_fights",
    "project_fights",
]
for column in count_columns:
    if column in county_summary.columns:
        county_summary[column] = county_summary[column].fillna(0).astype(int)
planned = (
    county_summary["proposed_count"]
    + county_summary["permitted_count"]
    + county_summary["under_construction_count"]
)
county_summary["planned_count"] = planned
county_summary["opposition_per_planned_facility"] = (
    county_summary["opposition_records"] / planned.where(planned.ne(0))
)
county_summary["opposition_records_per_100k"] = (
    county_summary["opposition_records"] / county_summary["population_2025"] * 100_000
)

# Label hubs and frontiers using the observed facility distribution.
county_summary["hub_frontier"] = "other"
is_frontier = planned.gt(0) & county_summary["operating_count"].le(1)
county_summary.loc[is_frontier, "hub_frontier"] = "frontier"
county_summary.loc[county_summary["operating_count"].ge(5), "hub_frontier"] = "hub"
print("Hub/frontier thresholds: hub >= 5 operating; frontier >= 1 planned and <= 1 operating")
print(county_summary["hub_frontier"].value_counts().to_string())

# Save county data and point joins for mapping and later summary statistics.
county_summary.to_file(clean / "county_summary.gpkg", layer="counties", driver="GPKG")
county_summary.drop(columns="geometry").reset_index().to_csv(
    clean / "county_summary.csv", index=False
)
registry_joined.drop(columns="geometry").to_csv(clean / "registry_county_joined.csv", index=False)
fight_joined.drop(columns="geometry").to_csv(clean / "opposition_county_joined.csv", index=False)
concern_counts.to_csv(clean / "county_concern_counts.csv", index=False)
nearest_sites.to_csv(clean / "proposed_nearest_operating.csv", index=False)
print(f"Saved county table: {len(county_summary):,} counties")
print(f"Saved joined facilities: {len(registry_joined):,} records")
print(f"Saved joined opposition: {len(fight_joined):,} records")
