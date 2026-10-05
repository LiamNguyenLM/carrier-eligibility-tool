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


# Round 14's audit profile -- the FIRST DP3 / Tenant Occupied profile this
# suite has ever exercised. Every prior profile was Owner Occupied, so the
# entire DP3 carrier set (Centauri, Steadily, HOAIC DP Guide, the DP3
# variants of Foremost/NatGen/Progressive/Sage) had never been through a
# single test. Note ppc "8A": a split/alpha protection class, which none of
# the numeric-PPC code paths had seen either.
AUDIT_R14_DP3_PROFILE = {
    "year_built": 1982,
    "roof_age": 25,
    "roof_type": "Composition Shingle",
    "roof_shape": "Flat",
    "construction_type": "Masonry Veneer",
    "plumbing_type": "Copper",
    "occupancy_type": "Tenant Occupied",
    "ownership_type": "Individual Owner",
    "coastal_tier": "Tier 2",
    "swimming_pool": "No Pool",
    "pool_accessories": "None",
    "has_dogs": "No",
    "aggressive_breed": "No",
    "solar_panels": "No",
    "ppc": "8A",
}


# Round 17: the base for Trust / LLC ownership coverage. Every profile above
# is "Individual Owner", so before round 17 no baseline, sweep or audit had
# ever exercised the Trust or LLC intake options at all.
#
# Deliberately CLEAN, so ownership is the only thing that can decline a
# carrier: PPC 3 (STANDARD's PPC 9 declines a large share of the family on its
# own and would drown any ownership effect), no pool, no solar, not coastal,
# newer roof, and "Architectural Shingle" rather than "Composition Shingle" so
# TWICO's documented 3-tab-vs-architectural ambiguity cannot intervene.
# Tests vary only ownership_type on top of this.
OWNERSHIP_BASE_PROFILE = {
    "year_built": 2012,
    "roof_age": 5,
    "roof_type": "Architectural Shingle",
    "roof_shape": "Gable",
    "construction_type": "Frame",
    "plumbing_type": "Copper",
    "occupancy_type": "Owner Occupied",
    "ownership_type": "Individual Owner",
    "coastal_tier": "Not Coastal",
    "swimming_pool": "No Pool",
    "pool_accessories": "None",
    "has_dogs": "No",
    "aggressive_breed": "No",
    "solar_panels": "No",
    "ppc": "3",
}


# Liam's live check on Railway, 27870a0 (round 26, 2026-10-05). Exactly what
# the form sent: the unchecked widgets keep their defaults (roof age 10,
# Composition Shingle, Gable, Frame, Not Coastal, no dogs), and only the
# topics in LIVE_CHECKED are considered. ZIP 75094 picks Collin (100%).
LIVE_PROFILE = {
    "year_built": 2007,
    "roof_age": 10,
    "roof_type": "Composition Shingle",
    "roof_shape": "Gable",
    "construction_type": "Frame",
    "plumbing_type": "PVC",
    "occupancy_type": "Owner Occupied",
    "ownership_type": "Individual Owner",
    "coastal_tier": "Not Coastal",
    "swimming_pool": "No Pool",
    "pool_accessories": "None",
    "pool_fence_4ft": False,
    "pool_gate_locking": False,
    "has_dogs": "No",
    "aggressive_breed": "No",
    "solar_panels": "Yes",
    "ppc": "3",
    "zip": "75094",
    "county": "Collin",
    "dwelling_amount": None,
    "dwelling_type": "House",
}
LIVE_CHECKED = ["ppc", "home_age", "pool", "plumbing", "solar", "county"]
