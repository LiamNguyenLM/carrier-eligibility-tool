"""Shared test data for verification scripts -- kept in one place so
diagnose_carrier.py and test_eligibility_matrix.py can't drift apart."""

# Same profile used across every audit round to date (rounds 1-6) -- keep
# using it so future runs and audits stay directly comparable.
STANDARD_PROFILE = {
    "year_built": 2009,
    "roof_age": 10,
    "roof_type": "Composition Shingle",
    "roof_shape": "Gable",
    "construction_type": "Frame",
    "plumbing_type": "PVC",
    "occupancy_type": "Owner Occupied",
    "ownership_type": "Individual Owner",
    "coastal_tier": "Not Coastal",
    "swimming_pool": "In Ground - Fenced",
    "pool_accessories": "None",
    "has_dogs": "No",
    "aggressive_breed": "No",
    "solar_panels": "No",
    "ppc": "9",
}


def normalize_carrier_name(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


def resolve_carrier(query_substring, all_carriers):
    target = normalize_carrier_name(query_substring)
    return sorted(c for c in all_carriers if target in normalize_carrier_name(c))
