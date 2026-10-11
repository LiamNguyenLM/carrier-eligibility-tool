"""Round 38 step 7e: shrink a failing profile to the fewest non-default answers that still fail the same check for the
same carrier, and save it as a fixture (verification/fuzz/fixtures/<name>.json) that test_fuzz_fixtures.py replays.

usage: python verification/fuzz/shrink.py <seed> <check> <carrier> <name> <class> <for_liam|fix> "<note>"
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import checks  # noqa: E402
import gen  # noqa: E402

# the plainest answer for each field; a shrink step resets one field to it (or drops an optional key)
PLAIN = {"ppc": "4", "fire_station_miles": 2.0, "hydrant_1000ft": "Yes", "coastal_tier": "Not Coastal",
         "occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "year_built": 2005, "roof_age": 5,
         "roof_type": "Composition Shingle", "roof_shape": "Gable", "construction_type": "Frame",
         "plumbing_type": "Copper", "swimming_pool": "No Pool", "pool_accessories": "None", "pool_fence_4ft": False,
         "pool_gate_locking": False, "has_dogs": "No", "dog_breeds": [], "solar_panels": "No", "zip": "",
         "county": "Travis", "dwelling_amount": 300000, "dwelling_type": "House"}
OPTIONAL = ("primary_home_carrier", "primary_home_miles", "trust_type", "solar_type", "solar_tesla",
            "harris_east_146", "losses_5yr", "loss_types", "loss_year", "losses_3yr", "electrical")


def fails(pd, checked, seed, check, carrier):
    got, _, _ = checks.check_profile(pd, checked, seed, only={check})
    return any(f["check"] == check and f["carrier"] == carrier for f in got)


def _consistent(pd):
    """Drop the follow-up keys app.py would not send for these answers."""
    pd = dict(pd)
    if pd.get("occupancy_type") not in ("Seasonal", "Secondary Home"):
        pd.pop("primary_home_carrier", None), pd.pop("primary_home_miles", None)
    if pd.get("ownership_type") != "Trust":
        pd.pop("trust_type", None)
    if pd.get("solar_panels") != "Yes":
        pd.pop("solar_type", None), pd.pop("solar_tesla", None)
    if pd.get("county") != "Harris":
        pd.pop("harris_east_146", None)
    if pd.get("losses_5yr") in (None, "", "0", "Unknown"):
        for k in ("loss_types", "loss_year", "losses_3yr"):
            pd.pop(k, None)
    if pd.get("swimming_pool") == "No Pool":
        pd.update(pool_accessories="None", pool_fence_4ft=False, pool_gate_locking=False)
    if pd.get("has_dogs") != "Yes":
        pd["dog_breeds"] = []
    pd["roof_age"] = min(pd.get("roof_age", 0), 2026 - int(pd.get("year_built", 2005)))
    return pd


def shrink(seed, check, carrier):
    pd, checked = gen.profile(seed)
    assert fails(pd, checked, seed, check, carrier), "does not reproduce"
    changed = True
    while changed:
        changed = False
        for k in list(OPTIONAL) + list(PLAIN):
            if k in OPTIONAL and k in pd:
                trial = _consistent({x: v for x, v in pd.items() if x != k})
            elif k in PLAIN and pd.get(k) != PLAIN[k]:
                trial = _consistent(dict(pd, **{k: PLAIN[k]}))
            else:
                continue
            if trial != pd and fails(trial, checked, seed, check, carrier):
                pd, changed = trial, True
        if sorted(checked) != sorted(gen.topics.TOPIC_KEYS):
            full = list(gen.topics.TOPIC_KEYS)
            if fails(pd, full, seed, check, carrier):
                checked, changed = full, True
    return pd, checked


def save(name, seed, check, carrier, cls, status, note):
    pd, checked = shrink(seed, check, carrier)
    path = os.path.join(HERE, "fixtures", f"{name}.json")
    json.dump({"name": name, "seed": seed, "check": check, "carrier": carrier, "class": cls, "status": status,
               "note": note, "pd": pd, "checked": checked}, open(path, "w", encoding="utf-8"), indent=1)
    return path


if __name__ == "__main__":
    print(save(sys.argv[4], int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[5], sys.argv[6], sys.argv[7]))
