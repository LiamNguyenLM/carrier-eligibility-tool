"""Round 21 Step 7: how often can picking one county for a ZIP change a
verdict? Zero API, read-only.

For every ZIP in zip_counties.csv that spans more than one county, ask whether
its counties DISAGREE on any county-keyed rule that is machine-readable today.
Every list below is parsed from the guide's own text at run time, not typed
from memory.

  sage            Sage ADDRESS rule (round 19): south of 31 N except Nueces,
                  plus the eight named East Texas counties
  sage_trium      the same without the Nueces exception (Trium)
  foremost_coast  Foremost "Coastal Areas: ... entirely restricted" (28)
  foremost_choice Foremost "entirely restricted for Foremost Choice Homeowners"
  foremost_tdp    Foremost "entirely restricted for the TDP1 and TDP3 Owner
                  Occupied programs"
  chubb_region    Chubb's three region tables (Coastal / Austin-San Antonio-
                  East-South / Dallas-Fort Worth-Northern); Harris is split by
                  territory, so it is its own value
  natgen_zone     NatGen Custom360's Coastal Zone 1 (Harris only for ZIPs
                  77571 / 77586), Zone 2 - Houston (Harris, Fort Bend), Zone 2
  progressive_nb  Progressive: "not accepting new business in Hidalgo or
                  Webb county"

Not county-keyed, so not here: Travelers (Hurricane Underwriting
Classification), Orion / Swyfft Lloyds / Progressive wind (distance from the
coast), and Mercury's coastal table, which is keyed by ZIP itself (see
handoff.md).

usage: python verification/analyze_zip_county_disagreement.py
"""
import os
import re
import sys
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import guides                      # noqa: E402
import intake_fields as f          # noqa: E402
from structured_rules import sage_county_in_territory  # noqa: E402

COUNTIES = f.TEXAS_COUNTIES


def names_in(text):
    """Texas county names appearing in text, longest first so 'Jim Wells'
    beats 'Wells'-style partials."""
    found = set()
    for c in sorted(COUNTIES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(c) + r"\b", text):
            found.add(c)
    return found


def between(text, start, end):
    i = text.index(start) + len(start)
    return text[i: text.index(end, i)]


def build_rules():
    fm = re.sub(r"\s+", " ", guides.guide_text("Foremost_DP3_and_HO3_-_07.01.2026"))
    coast = names_in(between(fm, "The following counties are entirely restricted. Exception: See requirements below.",
                             "Requirements:"))
    choice = names_in(between(fm, "entirely restricted for Foremost Choice Homeowners program:",
                              "The following counties"))
    tdp = names_in(between(fm, "entirely restricted for the TDP1 and TDP3 Owner Occupied programs:", "NOTE:"))

    ch = re.sub(r"\s+", " ", guides.guide_text("CHUBB_HO_-_05.22.2026"))
    ch_coast = names_in(between(ch, "Coastal areas are defined by the following counties:",
                                "Austin, San Antonio"))
    ch_south = names_in(between(ch, "East and South counties: Defined by the following counties: Defined by the following counties:",
                                "Dallas/Fort Worth, Collin County and rest of Northern counties:"))
    ch_north_text = ch.split("Dallas/Fort Worth, Collin County and rest of Northern counties: Defined by the following counties:", 1)[1]
    ch_north = names_in(ch_north_text[:6000])

    ng = re.sub(r"\s+", " ", guides.guide_text("NatGen_Custom360_HO3_-_06.25.2026"))
    i = ng.index("ZIP codes 77571 and 77586")
    z1_start = ng.rindex("Counties", 0, i)
    z2_start = ng.index("Counties", i)
    natgen = names_in(ng[z1_start: z2_start]) - {"Harris"}
    natgen_z2 = names_in(ng[z2_start: ng.index("Texas Landlord", z2_start)])

    def natgen_zone(c, z):
        if c in natgen or (c == "Harris" and z in ("77571", "77586")):
            return "Zone 1"
        if c in ("Harris", "Fort Bend"):
            return "Zone 2 - Houston"
        return "Zone 2" if c in natgen_z2 else "inland"

    def chubb_region(c):
        if c == "Harris":
            return "Harris (split by territory)"
        if c in ch_coast:
            return "Coastal"
        if c in ch_south:
            return "Austin/SA/East/South"
        if c in ch_north:
            return "DFW/Northern"
        return "not listed"

    lat = f.COUNTY_MAX_LATITUDE
    rules = {
        "sage": lambda c, z: sage_county_in_territory(c, lat, nueces_excluded=True),
        "sage_trium": lambda c, z: sage_county_in_territory(c, lat, nueces_excluded=False),
        "foremost_coast": lambda c, z: c in coast,
        "foremost_choice": lambda c, z: c in choice,
        "foremost_tdp": lambda c, z: c in tdp,
        "chubb_region": lambda c, z: chubb_region(c),
        "natgen_zone": natgen_zone,
        "progressive_nb": lambda c, z: c in ("Hidalgo", "Webb"),
    }
    sizes = {"foremost_coast": len(coast), "foremost_choice": len(choice), "foremost_tdp": len(tdp),
             "chubb_coastal": len(ch_coast), "chubb_south": len(ch_south), "chubb_north": len(ch_north),
             "natgen_zone1": len(natgen), "natgen_zone2": len(natgen_z2)}
    return rules, sizes


def main():
    rules, sizes = build_rules()
    table = f.ZIP_COUNTIES
    multi = {z: f.counties_for_zip(z) for z, v in table.items() if len(v) > 1}
    print(f"ZIPs in table: {len(table)}; spanning more than one county: {len(multi)} "
          f"({len(multi) / len(table):.0%})")
    print("parsed list sizes:", sizes)
    bands = Counter()
    for z, v in multi.items():
        top = v[0][1] / sum(s for _, s in v)        # share of the ZIP's Texas land
        bands["95%+" if top >= .95 else "80-95%" if top >= .80 else "60-80%" if top >= .60 else "under 60%"] += 1
    print("top county's share, multi-county ZIPs:",
          {k: bands[k] for k in ("95%+", "80-95%", "60-80%", "under 60%")})
    disagree, by_rule = {}, Counter()
    for z, v in sorted(multi.items()):
        hit = [name for name, rule in rules.items() if len({str(rule(c, z)) for c, _ in v}) > 1]
        if hit:
            disagree[z] = hit
            by_rule.update(hit)
    print(f"multi-county ZIPs whose counties DISAGREE on at least one rule: {len(disagree)} "
          f"of {len(multi)} ({len(disagree) / len(table):.1%} of all ZIPs)")
    print("by rule:", dict(by_rule.most_common()))
    sage_pick = [z for z in disagree if "sage" in disagree[z]]
    weak = [z for z in disagree if multi[z][0][1] / sum(s for _, s in multi[z]) < .80]
    print(f"  of those, the top county holds under 80% of the land: {len(weak)}")
    print("first 20:")
    for z in list(disagree)[:20]:
        parts = ", ".join(f"{c} {s:.0%}" for c, s in multi[z])
        print(f"  {z}: {parts}  -> {', '.join(disagree[z])}")
    return disagree


if __name__ == "__main__":
    main()
