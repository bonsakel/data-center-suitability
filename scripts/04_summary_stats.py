from pathlib import Path

import pandas as pd


# Find the prepared county and concern tables from the project root.
project = Path(__file__).resolve().parents[1]
clean = project / "data" / "clean"
county = pd.read_csv(clean / "county_summary.csv", dtype={"GEOID": str})
concerns = pd.read_csv(clean / "county_concern_counts.csv", dtype={"GEOID": str})
fights = pd.read_csv(clean / "opposition_county_joined.csv", dtype={"GEOID": str})

# Add Census regions so concern patterns can be compared geographically.
regions = {
    "Northeast": {"CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"},
    "Midwest": {"IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"},
    "South": {"DE", "MD", "VA", "WV", "KY", "TN", "NC", "SC", "GA", "FL", "AL", "MS", "AR", "LA", "OK", "TX"},
    "West": {"AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"},
}
state_region = {state: region for region, states in regions.items() for state in states}
county["region"] = county["STUSPS"].map(state_region)

# Summarize the selected hub and frontier groups using pooled rates.
groups = county.loc[county["hub_frontier"].isin(["hub", "frontier"])].copy()
group_stats = groups.groupby("hub_frontier").agg(
    counties=("GEOID", "size"),
    planned_facilities=("planned_count", "sum"),
    opposition_records=("opposition_records", "sum"),
    opposition_fights=("opposition_fights", "sum"),
    project_fights=("project_fights", "sum"),
    population=("population_2025", "sum"),
).reset_index()
group_stats["records_per_planned_facility"] = (
    group_stats["opposition_records"] / group_stats["planned_facilities"]
)
group_stats["fights_per_planned_facility"] = (
    group_stats["opposition_fights"] / group_stats["planned_facilities"]
)
group_stats["records_per_100k_people"] = (
    group_stats["opposition_records"] / group_stats["population"] * 100_000
)

# Calculate county-rate medians only where a planned facility exists.
county_rates = groups.loc[groups["planned_count"].gt(0)].groupby("hub_frontier")[
    "opposition_per_planned_facility"
].median()
group_stats["median_county_records_per_planned_facility"] = group_stats[
    "hub_frontier"
].map(county_rates)
print("Hub/frontier summary (selected cutoffs: hub >= 5; frontier <= 1 operating):")
print(group_stats.to_string(index=False))
group_stats.to_csv(clean / "hub_frontier_summary.csv", index=False)

# Test alternative operating-count cutoffs to show whether the comparison is sensitive.
sensitivity = []
for hub_cutoff in [3, 5, 10]:
    for frontier_max in [0, 1, 2]:
        for label in ["hub", "frontier"]:
            if label == "hub":
                subset = county.loc[county["operating_count"].ge(hub_cutoff)]
            else:
                subset = county.loc[
                    county["planned_count"].gt(0)
                    & county["operating_count"].le(frontier_max)
                ]
            planned_count = subset["planned_count"].sum()
            records = subset["opposition_records"].sum()
            sensitivity.append(
                {
                    "hub_cutoff": hub_cutoff,
                    "frontier_max_operating": frontier_max,
                    "group": label,
                    "counties": len(subset),
                    "planned_facilities": planned_count,
                    "opposition_records": records,
                    "records_per_planned_facility": (
                        records / planned_count if planned_count else None
                    ),
                }
            )
sensitivity = pd.DataFrame(sensitivity)
print("\nThreshold sensitivity:")
print(sensitivity.to_string(index=False))
sensitivity.to_csv(clean / "hub_frontier_threshold_sensitivity.csv", index=False)

# Report concern mentions rather than implying each action has only one concern.
concerns = concerns.merge(
    county[["GEOID", "hub_frontier", "region"]], on="GEOID", how="left"
)
concerns = concerns.loc[concerns["hub_frontier"].isin(["hub", "frontier"])]
concern_summary = concerns.groupby(
    ["hub_frontier", "region", "issue_category"], as_index=False
)["count"].sum()
concern_summary["share_of_concern_mentions"] = concern_summary["count"] / concern_summary.groupby(
    ["hub_frontier", "region"]
)["count"].transform("sum")
concern_summary.to_csv(clean / "concern_shares_by_region.csv", index=False)
print("\nConcern mentions by hub/frontier and Census region:")
print(concern_summary.to_string(index=False))

# Summarize source-coded outcomes while keeping the coding caveat visible.
fights = fights.merge(
    county[["GEOID", "hub_frontier"]], on="GEOID", how="left"
)
outcome = fights.loc[fights["hub_frontier"].isin(["hub", "frontier"])].copy()
outcome["community_outcome"] = outcome["community_outcome"].fillna("unclassified")
outcome_summary = outcome.groupby(
    ["hub_frontier", "community_outcome"], as_index=False
).size().rename(columns={"size": "records"})
outcome_summary["share_of_records"] = outcome_summary["records"] / outcome_summary.groupby(
    "hub_frontier"
)["records"].transform("sum")
resolved = outcome.loc[outcome["community_outcome"].isin(["win", "loss", "mixed"])]
resolved_counts = resolved.groupby(["hub_frontier", "community_outcome"]).size().unstack(
    fill_value=0
)
win_share = resolved_counts["win"] / resolved_counts.sum(axis=1)
outcome_summary["win_share_of_resolved"] = outcome_summary["hub_frontier"].map(win_share)
outcome_summary.to_csv(clean / "tracker_outcomes_by_hub_frontier.csv", index=False)
print("\nTracker-coded outcomes (descriptive; see data_limits.md):")
print(outcome_summary.to_string(index=False))

# Compare region totals for counts and per-person rates.
region_stats = county.groupby("region", as_index=False).agg(
    counties=("GEOID", "size"),
    population=("population_2025", "sum"),
    opposition_records=("opposition_records", "sum"),
    planned_facilities=("planned_count", "sum"),
)
region_stats["records_per_100k_people"] = (
    region_stats["opposition_records"] / region_stats["population"] * 100_000
)
region_stats.to_csv(clean / "opposition_by_region.csv", index=False)
print("\nSaved summary tables in data/clean/")
