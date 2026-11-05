import json
from pathlib import Path

import pandas as pd


# Print row counts so each cleaning decision is easy to explain.
def print_counts(step, before, after, reason):
    print(
        f"{step}: before={before:,}, after={after:,}, "
        f"dropped={before - after:,} ({reason})"
    )


# Keep URLs usable when source entries include titles as well as links.
def flatten_list(values):
    if not isinstance(values, list):
        return values
    items = []
    for value in values:
        if isinstance(value, dict) and "url" in value:
            items.append(str(value["url"]))
        else:
            items.append(str(value))
    return "; ".join(items)


# Find the raw file and output folder from the project root.
project = Path(__file__).resolve().parents[1]
raw_path = project / "data" / "raw" / "opposition" / "site" / "data" / "fights.json"
clean_path = project / "data" / "clean" / "opposition_local_clean.csv"
clean_path.parent.mkdir(parents=True, exist_ok=True)

# Load the source records without changing the raw download.
with raw_path.open(encoding="utf-8") as file:
    fights = pd.DataFrame(json.load(file))
print(f"Loaded source records: {len(fights):,}")

# Keep only local records because the analysis is county-focused.
before = len(fights)
local = fights.loc[fights["scope"].eq("local")].copy()
print_counts("Keep local records", before, len(local), "statewide and federal records excluded")

# Remove records without usable coordinates so they can be mapped later.
before = len(local)
local["lat"] = pd.to_numeric(local["lat"], errors="coerce")
local["lng"] = pd.to_numeric(local["lng"], errors="coerce")
has_coordinates = local["lat"].between(-90, 90) & local["lng"].between(-180, 180)
local = local.loc[has_coordinates].copy()
print_counts("Keep usable coordinates", before, len(local), "missing, nonnumeric, or out-of-range coordinates")

# Turn list values into readable text while preserving missing values.
before = len(local)
list_fields = ["issue_category", "action_type", "sources", "opposition_groups", "flags", "sponsors"]
for field in list_fields:
    if field in local.columns:
        local[field] = local[field].apply(flatten_list)
print_counts("Flatten list fields", before, len(local), "no records dropped")

# Label project-specific records first, then clear policy actions, then other local actions.
before = len(local)
has_project = (
    local["company"].fillna("").astype(str).str.strip().ne("")
    | local["project_name"].fillna("").astype(str).str.strip().ne("")
)
policy_actions = {
    "moratorium",
    "zoning_restriction",
    "ordinance",
    "legislation",
    "regulatory_action",
    "utility_regulation",
    "permit_denial",
    "executive_action",
    "executive_order",
}
action_lists = local["action_type"].fillna("").str.split("; ")
is_policy_response = action_lists.apply(
    lambda actions: any(action in policy_actions for action in actions)
)
local["fight_type"] = "other_local_action"
local.loc[is_policy_response, "fight_type"] = "policy_response"
local.loc[has_project, "fight_type"] = "project_specific_fight"
print_counts("Add fight type", before, len(local), "no records dropped")
print("Fight type counts:")
print(local["fight_type"].value_counts().to_string())

# Save the cleaned local records for later analysis.
local.to_csv(clean_path, index=False)
print(f"Saved {len(local):,} records to {clean_path.relative_to(project)}")
