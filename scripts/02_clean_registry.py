from pathlib import Path

import pandas as pd


# Print row counts so each cleaning decision is easy to explain.
def print_counts(step, before, after, reason):
    print(
        f"{step}: before={before:,}, after={after:,}, "
        f"dropped={before - after:,} ({reason})"
    )


# Find the raw file and output folder from the project root.
project = Path(__file__).resolve().parents[1]
raw_path = project / "data" / "raw" / "registry" / "data-centers.csv"
clean_path = project / "data" / "clean" / "registry_clean.csv"
clean_path.parent.mkdir(parents=True, exist_ok=True)

# Load the registry and print its actual size before filtering.
registry = pd.read_csv(raw_path)
print(f"Loaded registry records: {len(registry):,}")

# Keep data centers because crypto-mining sites are outside this project.
before = len(registry)
registry = registry.loc[registry["facility_type"].eq("data_center")].copy()
print_counts("Keep data centers", before, len(registry), "crypto-mining records excluded")

# Keep the 50 states and exclude DC and territories.
states = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}
before = len(registry)
registry = registry.loc[registry["state"].isin(states)].copy()
print_counts("Keep the 50 states", before, len(registry), "DC and territory records excluded")

# Keep records with usable coordinates for mapping and county assignment.
before = len(registry)
registry["latitude"] = pd.to_numeric(registry["latitude"], errors="coerce")
registry["longitude"] = pd.to_numeric(registry["longitude"], errors="coerce")
has_coordinates = registry["latitude"].between(-90, 90) & registry["longitude"].between(-180, 180)
registry = registry.loc[has_coordinates].copy()
print_counts("Keep usable coordinates", before, len(registry), "missing, nonnumeric, or out-of-range coordinates")

# Give each observed status a consistent label for the analysis.
before = len(registry)
status_names = {
    "operational": "operating",
    "under_construction": "under_construction",
    "permitted": "permitted",
    "proposed": "proposed",
    "cancelled": "cancelled",
}
registry["status_clean"] = registry["status"].map(status_names).fillna("other")
print_counts("Clean status labels", before, len(registry), "no records dropped")
print("Status counts:")
print(registry["status_clean"].value_counts(dropna=False).to_string())

# Save the cleaned facilities without changing the raw download.
registry.to_csv(clean_path, index=False)
print(f"Saved {len(registry):,} records to {clean_path.relative_to(project)}")
