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

# The alternate profile introduced in round 10 -- a genuinely different
# customer (different PPC, home age, roof age, no pool, solar panels
# present) used to check that fixes generalize past the one profile every
# prior round reused.
ALT_PROFILE = {
    "year_built": 1994,
    "roof_age": 14,
    "roof_type": "Composition Shingle",
    "roof_shape": "Gable",
    "construction_type": "Frame",
    "plumbing_type": "PVC",
    "occupancy_type": "Owner Occupied",
    "ownership_type": "Individual Owner",
    "coastal_tier": "Not Coastal",
    "swimming_pool": "No Pool",
    "pool_accessories": "None",
    "has_dogs": "No",
    "aggressive_breed": "No",
    "solar_panels": "Yes",
    "ppc": "1",
}

# Round 12's audit profile -- a third, again genuinely different customer
# (mid-range PPC, coastal, tile roof, copper plumbing, no pool/solar) used
# to check that round 12's fixes (Sage FPC wiring, ARI cross-contamination,
# Liberty Mutual AND-conditioned generalization, TWICO roof gating) hold
# outside the two profiles every prior round reused.
COASTAL_PPC4_PROFILE = {
    "year_built": 2004,
    "roof_age": 16,
    "roof_type": "Tile",
    "roof_shape": "Gable",
    "construction_type": "Frame",
    "plumbing_type": "Copper",
    "occupancy_type": "Owner Occupied",
    "ownership_type": "Individual Owner",
    "coastal_tier": "Tier 3",
    "swimming_pool": "No Pool",
    "pool_accessories": "None",
    "has_dogs": "No",
    "aggressive_breed": "No",
    "solar_panels": "No",
    "ppc": "4",
}


def normalize_carrier_name(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


def resolve_carrier(query_substring, all_carriers):
    target = normalize_carrier_name(query_substring)
    return sorted(c for c in all_carriers if target in normalize_carrier_name(c))


# Round 13's live-app audit profile -- the property from the manual audit
# run that produced round 13's P2/P3/P4 findings. Deliberately stacks the
# three features that round's findings turned on, none of which any earlier
# profile combined: a roof age where TWICO's two composition sub-type bands
# genuinely DIVERGE (21yr = EXCLUDED under 3-tab, ACV under architectural --
# see twico_roof_settlement), a pool whose intake value is the bare generic
# "In Ground - Fenced" with no height/gate detail, and mounted solar panels.
AUDIT_R13_PROFILE = {
    "year_built": 2004,
    "roof_age": 21,
    "roof_type": "Composition Shingle",
    "roof_shape": "Gable",
    "construction_type": "Frame",
    "plumbing_type": "Copper",
    "occupancy_type": "Owner Occupied",
    "ownership_type": "Individual Owner",
    "coastal_tier": "Tier 3",
    "swimming_pool": "In Ground - Fenced",
    "pool_accessories": "None",
    "has_dogs": "Yes",
    "aggressive_breed": "No",
    "solar_panels": "Yes",
    "ppc": "4",
}
