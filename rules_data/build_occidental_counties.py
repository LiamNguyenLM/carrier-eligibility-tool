"""Build rules_data/occidental_counties.csv: SageSure Occidental HO3's address rule (OCC-001, p.3), county by county
(round 40 step 2, Liam 2026-10-16).

"Property must be located in: South Texas (meaning a county located entirely south of 31 degrees North) except
Nueces county, or One of the following counties in East Texas: Bell, Falls, Robertson, Leon, Madison, Houston,
Trinity, and Polk." -- the OCC-002 counties are part of the same either/or rule.

"Entirely south of 31 N" is read from each county's northernmost latitude in texas_counties.csv (U.S. Census Bureau
2023 Cartographic Boundary File cb_2023_us_county_500k, the max over every polygon vertex, built 2026-09-30) -- the
same data structured_rules.sage_county_in_territory and the map's south_of_31 fact read, so this list and the card
can never disagree (verification/test_natgen_c360_occidental.py checks every county). The 1:500,000 file is
generalised; the closest county to the line (Brazos, 30.974) is 0.026 degrees (about 2.9 km) from it, far more than
the generalisation.

usage: python rules_data/build_occidental_counties.py
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "..", "texas_counties.csv")
OUT = os.path.join(HERE, "occidental_counties.csv")
EAST_TEXAS = ("Bell", "Falls", "Robertson", "Leon", "Madison", "Houston", "Trinity", "Polk")
NEAR = 0.15          # the report lists every county whose northern edge is this close to 31 N


def counties():
    with open(SOURCE, encoding="utf-8") as fh:
        return {r["county"]: float(r["max_latitude"]) for r in csv.DictReader(l for l in fh if not l.startswith("#"))}


def decide(county, lat):
    if county in EAST_TEXAS:
        return "IN", "one of the eight named East Texas counties"
    if county == "Nueces":
        return "OUT", "south of 31 N, but the guide excepts Nueces"
    if lat < 31.0:
        return "IN", "entirely south of 31 N"
    return "OUT", "reaches 31 N or north of it"


def main():
    rows = sorted(counties().items())
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write("# SageSure Occidental HO3 (Sage_-_Occidental_HO3_-_12.02.2025, revised 12/2/2025), OCC-001 / OCC-002, "
                 "p.3. Built 2026-10-16 by rules_data/build_occidental_counties.py from texas_counties.csv (U.S. Census "
                 "Bureau 2023 Cartographic Boundary File cb_2023_us_county_500k, northernmost vertex latitude, NAD83, "
                 "built 2026-09-30).\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["county", "max_latitude", "occidental", "why"])
        for county, lat in rows:
            w.writerow([county, f"{lat:.5f}", *decide(county, lat)])
    inside = [c for c, lat in rows if decide(c, lat)[0] == "IN"]
    print(f"wrote {OUT}: {len(rows)} counties, {len(inside)} IN")
    print("near 31 N:")
    for c, lat in sorted(rows, key=lambda x: x[1]):
        if abs(lat - 31.0) <= NEAR:
            print(f"  {c:14s} {lat:.5f}  {decide(c, lat)[0]}  {decide(c, lat)[1]}")
    for c in ("Harris", "Fort Bend", "Bexar", "Galveston", "Travis", "Dallas", "Tarrant", "Nueces"):
        print(f"  check {c:10s} {dict(rows)[c]:.5f} {decide(c, dict(rows)[c])[0]}")


if __name__ == "__main__":
    main()
