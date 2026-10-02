"""Build zip_counties.csv: Texas ZIP -> [(county, share)], for the ZIP box
(round 21, Liam 2026-10-02). Run by hand at BUILD time; the app never makes a
network call for this.

Two sources, never mixed in one table:

  A) HUD-USPS ZIP Code Crosswalk API (preferred). USPS ZIPs, share =
     res_ratio, the share of the ZIP's RESIDENTIAL addresses in each county.
     Needs a token in the HUD_API_TOKEN environment variable. The token is
     read here only, never printed, never written anywhere.

         python build_zip_county.py hud

  B) Census 2020 ZCTA-to-county relationship file (fallback, no key).
     share = AREALAND_PART / AREALAND_ZCTA5_20, the share of the ZCTA's LAND
     in each county. ZCTAs are not exactly USPS ZIPs (PO-box-only ZIPs have
     none), and land is a worse stand-in than residential addresses for
     where a house is.

         python build_zip_county.py census [path to tab20_zcta520_county20_natl.txt]

The output keeps Texas counties only (state FIPS 48). A ZCTA that crosses a
state line keeps its Texas parts, with shares of its WHOLE land area, so
they can sum to less than 1.
"""
import csv
import datetime
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "zip_counties.csv")
CENSUS_URL = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
              "tab20_zcta520_county20_natl.txt")
HUD_URL = "https://www.huduser.gov/hudapi/public/usps?type=2&query=TX"


def texas_counties_by_geoid():
    with open(os.path.join(HERE, "texas_counties.csv"), encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        return {r["geoid"]: r["county"] for r in rows}


def from_census(path):
    names = texas_counties_by_geoid()
    table = {}
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter="|"):
            z, g = r["GEOID_ZCTA5_20"], r["GEOID_COUNTY_20"]
            if not z or not g.startswith("48"):
                continue
            land = int(r["AREALAND_ZCTA5_20"] or 0)
            part = int(r["AREALAND_PART"] or 0)
            if land <= 0 or part <= 0:
                continue                         # no land in this part: no house can be there
            table.setdefault(z, []).append((names[g], part / land))
    source = (f"Census 2020 ZCTA-to-county relationship file ({CENSUS_URL}, file dated "
              "2021-12-09)")
    share = "AREALAND_PART / AREALAND_ZCTA5_20 (share of the ZCTA's land area in the county)"
    return table, source, share


def from_hud():
    token = os.environ.get("HUD_API_TOKEN")
    if not token:
        sys.exit("HUD_API_TOKEN is not set; use the census source instead.")
    names = texas_counties_by_geoid()
    req = urllib.request.Request(HUD_URL, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    meta = data.get("data", {})
    table = {}
    for r in meta.get("results", []):
        g, z = str(r["geoid"]), str(r["zip"]).zfill(5)
        if g.startswith("48") and float(r.get("res_ratio") or 0) > 0:
            table.setdefault(z, []).append((names[g], float(r["res_ratio"])))
    source = (f"HUD-USPS ZIP Code Crosswalk API, type=2 (zip-county), query=TX, "
              f"year {meta.get('year')} quarter {meta.get('quarter')}")
    share = "res_ratio (share of the ZIP's residential addresses in the county)"
    return table, source, share


def write(table, source, share):
    today = datetime.date.today().isoformat()
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"# source: {source}\n# built: {today}\n# share: {share}\n"
                 "# pick: largest share, tie alphabetical (intake_fields.county_for_zip)\n")
        w = csv.writer(fh)
        w.writerow(["zip", "county", "share"])
        for z in sorted(table):
            for county, s in sorted(table[z], key=lambda cs: (-cs[1], cs[0])):
                w.writerow([z, county, f"{s:.6f}"])
    print(f"wrote {OUT}: {len(table)} ZIPs, {sum(len(v) for v in table.values())} rows")


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "census"
    if kind == "hud":
        write(*from_hud())
    else:
        path = sys.argv[2] if len(sys.argv) > 2 else None
        if path is None:
            path = os.path.join(HERE, "_census_zcta_county.txt")
            urllib.request.urlretrieve(CENSUS_URL, path)
        write(*from_census(path))
