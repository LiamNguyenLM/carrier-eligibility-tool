"""Round 38 step 7a (Liam, 2026-10-11): seeded random profiles for the self-audit, built the way app.py builds
property_details -- every value one the form can produce, a key present only when the form shows its question.

usage: from gen import profile; pd, checked = profile(seed)
       python verification/fuzz/gen.py <seed> [n]      (prints n profiles as JSON lines)

About 3 in 4 profiles are realistic (common answers, a real ZIP and its county, a roof no older than the home); the
rest lean on edge cases (blank / Unknown answers, unticked topics, the oldest and newest homes, a roof as old as the
home, coastal counties, every loss and electrical answer)."""
import csv
import json
import os
import random
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
import intake_fields  # noqa: E402
import topics  # noqa: E402

YEAR = 2026
PPC = ("N/A", "1", "2", "3", "4", "5", "6", "7", "8", "8A", "8B", "9", "10")
COASTAL = ("Not Coastal", "Tier 1", "Tier 2", "Tier 3")
OCCUPANCY = ("Owner Occupied", "Tenant Occupied", "Seasonal", "Vacant", "Secondary Home")
CONSTRUCTION = ("Frame", "Masonry", "Masonry Veneer", "Superior", "Manufactured/Mobile")
ROOF_SHAPES = ("Gable", "Hip", "Flat", "Gambrel", "Mansard", "Other")
POOLS = ("No Pool", "Above Ground - Fenced", "Above Ground - Unfenced", "In Ground - Fenced", "In Ground - Unfenced")
POOL_EXTRAS = ("None", "Slide only", "Diving board only", "Both slide and diving board")
COASTAL_COUNTIES = ("Harris", "Galveston", "Brazoria", "Fort Bend", "Nueces", "Cameron", "Jefferson", "Montgomery",
                    "Chambers", "Matagorda", "Aransas", "Orange", "Hidalgo", "Victoria")


def _zips():
    out = []
    with open(os.path.join(ROOT, "zip_counties.csv"), encoding="utf-8") as fh:
        for row in csv.reader(l for l in fh if not l.startswith("#")):
            if row and row[0].isdigit():
                out.append(row[0])
    return sorted(set(out))


ZIPS = _zips()


def _pick(rng, values, weights=None):
    return rng.choices(values, weights=weights)[0] if weights else rng.choice(values)


def profile(seed):
    """(property_details, checked_topics) for one seed; the same seed always gives the same profile."""
    rng = random.Random(seed)
    edge = rng.random() < 0.25
    pd = {}
    pd["ppc"] = _pick(rng, PPC, None if edge else [1, 2, 3, 6, 8, 8, 6, 5, 3, 2, 2, 2, 2])
    station = None if (edge and rng.random() < 0.5) or rng.random() < 0.35 else round(rng.choice(
        [0.5, 1, 2, 3, 4, 4.9, 5, 5.1, 6, 7, 8, 10, 15]) if edge else rng.uniform(0.3, 9), 1)
    pd["fire_station_miles"] = station
    pd["hydrant_1000ft"] = _pick(rng, intake_fields.HYDRANT_CHOICES, None if edge else [3, 6, 1])
    pd["coastal_tier"] = _pick(rng, COASTAL, None if edge else [6, 1, 2, 1])
    pd["occupancy_type"] = _pick(rng, OCCUPANCY, None if edge else [12, 5, 1, 1, 1])
    pd["ownership_type"] = _pick(rng, intake_fields.OWNERSHIP_TYPES, None if edge else [12, 2, 3, 1, 1])
    year = rng.choice([1800, 1900, 1920, 1950, 1979, 1980, 1990, 2000, 2010, 2025, 2026]) if edge else \
        rng.randint(1950, 2025)
    pd["year_built"] = year
    age = YEAR - year
    pd["roof_age"] = (rng.choice([0, age, min(age, 100), 1, 10, 15, 20, 25, 26, 30, 40]) if edge
                      else rng.randint(0, max(0, min(age, 30))))
    pd["roof_type"] = _pick(rng, intake_fields.ROOF_TYPES)
    pd["roof_shape"] = _pick(rng, ROOF_SHAPES, None if edge else [6, 4, 1, 1, 1, 1])
    pd["construction_type"] = _pick(rng, CONSTRUCTION, None if edge else [8, 3, 4, 1, 1])
    pd["plumbing_type"] = _pick(rng, intake_fields.PLUMBING_TYPES)
    pool = _pick(rng, POOLS, None if edge else [12, 1, 1, 3, 1])
    pd["swimming_pool"] = pool
    pd["pool_accessories"] = "None" if pool == "No Pool" else _pick(rng, POOL_EXTRAS)
    fenced = pool in intake_fields.FENCED_POOL_VALUES
    pd["pool_fence_4ft"] = fenced and rng.random() < 0.5
    pd["pool_gate_locking"] = fenced and rng.random() < 0.5
    dogs = rng.random() < (0.5 if edge else 0.3)
    pd["has_dogs"] = "Yes" if dogs else "No"
    pd["dog_breeds"] = (rng.sample(list(intake_fields.DOG_CHOICES), rng.randint(0, 2)) if dogs else [])
    solar = rng.random() < (0.4 if edge else 0.1)
    pd["solar_panels"] = "Yes" if solar else "No"
    pd["zip"], pd["county"] = "", ""
    if not (edge and rng.random() < 0.3):
        if rng.random() < (0.5 if edge else 0.25):
            pd["county"] = rng.choice(COASTAL_COUNTIES)
        else:
            z = rng.choice(ZIPS)
            county = intake_fields.county_for_zip(z)[0]
            if county:
                pd["zip"], pd["county"] = z, county
            else:
                pd["county"] = rng.choice(intake_fields.TEXAS_COUNTIES)
    if not edge:     # a realistic profile's coastal tier matches its county (second reader, hour 1: Tier 1 in Ector)
        coastal = pd["county"] in COASTAL_COUNTIES or pd["county"] in ("Kleberg", "Kenedy", "Willacy", "Refugio",
                                                                       "San Patricio", "Calhoun", "Jackson")
        pd["coastal_tier"] = _pick(rng, COASTAL[1:], [2, 3, 2]) if coastal else (
            "Not Coastal" if pd["county"] else pd["coastal_tier"])
    pd["dwelling_amount"] = (None if rng.random() < (0.5 if edge else 0.3) else
                             rng.choice([50000, 100000, 249999, 250000, 500000, 750000, 750001, 1000000, 2000000,
                                         3000000]) if edge else rng.randrange(120000, 900000, 5000))
    pd["dwelling_type"] = _pick(rng, intake_fields.DWELLING_TYPES[1:], None if edge else [10, 2, 1])
    # the questions shown only for some answers (absent otherwise, as in app.py)
    if pd["occupancy_type"] in intake_fields.OWNERS_OTHER_HOMES:
        pd["primary_home_carrier"] = _pick(rng, intake_fields.PRIMARY_HOME_CHOICES)
        pd["primary_home_miles"] = rng.choice([None, 2, 15, 40, 120])
    if pd["ownership_type"] == "Trust":
        pd["trust_type"] = _pick(rng, intake_fields.TRUST_TYPES)
    if solar:
        pd["solar_type"] = _pick(rng, intake_fields.SOLAR_TYPES)
        pd["solar_tesla"] = _pick(rng, intake_fields.TESLA_CHOICES)
    if pd["county"] == "Harris":
        pd["harris_east_146"] = _pick(rng, intake_fields.HARRIS_146_CHOICES)
    losses = _pick(rng, intake_fields.LOSS_COUNTS, None if edge else [6, 4, 2, 1, 1, 1])
    if losses:
        pd["losses_5yr"] = losses
        if losses in ("1", "2", "3 or more"):
            types = rng.sample(list(intake_fields.LOSS_TYPES), rng.randint(0, 2))
            if types:
                pd["loss_types"] = types
            if rng.random() < 0.8:
                pd["loss_year"] = rng.randint(YEAR - 5, YEAR)
            in3 = _pick(rng, intake_fields.LOSS_3YR_COUNTS)
            if in3:
                pd["losses_3yr"] = in3
    if rng.random() < (0.6 if edge else 0.3):
        picked = rng.sample(list(intake_fields.ELECTRICAL_CHOICES), rng.randint(1, 2))
        pd["electrical"] = picked
    # the "Check this" boxes: all ticked for most profiles; some unticked otherwise
    keys = list(topics.TOPIC_KEYS)
    if rng.random() < (0.5 if edge else 0.15):
        checked = [k for k in keys if rng.random() < 0.7]
    else:
        checked = keys
    # Round 39: a rental's questions (as app.py). Drawn last, so every earlier answer of a seed is unchanged.
    if pd["occupancy_type"] == intake_fields.RENTAL_OCCUPANCY:
        pd["primary_home_carrier"] = _pick(rng, intake_fields.PRIMARY_HOME_CHOICES,
                                           None if edge else [4] + [1] * (len(intake_fields.PRIMARY_HOME_CHOICES) - 1))
        for key, choices in (("rental_units_total", intake_fields.RENTAL_UNITS_CHOICES),
                             ("rental_term", intake_fields.RENTAL_TERM_CHOICES)):
            v = _pick(rng, choices)
            if v:
                pd[key] = v
    return pd, checked


if __name__ == "__main__":
    seed, n = int(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 1
    for s in range(seed, seed + n):
        print(json.dumps({"seed": s, "pd": profile(s)[0], "checked": profile(s)[1]}))
