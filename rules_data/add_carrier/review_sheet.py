"""Add a carrier, step 6 (pilot_structured_rules/ADD_CARRIER.md): the one-page review sheet a person signs off before
the carrier's table is switched on -- every deciding row and how the tool decides it, then the tool's verdict on a
standard set of homes, with a blank column for the reviewer. Zero API (rules_evaluator only).

usage: python rules_data/add_carrier/review_sheet.py <program name> <out.md>
       e.g. python rules_data/add_carrier/review_sheet.py The_Hartford_HO3_-_07.09.2026 review_hartford.md
The program must already be registered (rules_evaluator.BATCHES)."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import cards  # noqa: E402
import display_names  # noqa: E402
import intake_fields as I  # noqa: E402
import rules_evaluator as rv  # noqa: E402

OWN = {"year_built": 1995, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
       "construction_type": "Frame", "plumbing_type": "PVC", "occupancy_type": "Owner Occupied",
       "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
       "pool_accessories": "None", "pool_fence_4ft": False, "pool_gate_locking": False, "has_dogs": "No",
       "dog_breeds": [], "solar_panels": "No", "ppc": "4", "fire_station_miles": 3.0, "hydrant_1000ft": "Yes",
       "zip": "", "county": "Travis", "dwelling_amount": 400000, "dwelling_type": "House", "losses_5yr": "0",
       "electrical": ["Circuit breakers"]}
RENT = dict(OWN, occupancy_type="Tenant Occupied")
L1 = dict(losses_5yr="1", losses_3yr="1", loss_year=2025)
SCENARIOS = [
    ("A plain owner's home (Travis, $400K, 1995, 10-yr composition roof)", OWN, {}),
    ("Harris County, Tier 2", OWN, {"county": "Harris", "coastal_tier": "Tier 2", "harris_east_146": "No"}),
    ("Galveston, Tier 1", OWN, {"county": "Galveston", "coastal_tier": "Tier 1"}),
    ("Coverage A $1,500,000", OWN, {"dwelling_amount": 1500000}),
    ("Coverage A $3,000,000", OWN, {"dwelling_amount": 3000000}),
    ("PPC 10", OWN, {"ppc": "10", "fire_station_miles": 9.0}),
    ("Roof 23 years, built 1995", OWN, {"roof_age": 23}),
    ("Flat roof", OWN, {"roof_shape": "Flat"}),
    ("Wood shake roof", OWN, {"roof_type": I.ROOF_WOOD}),
    ("Built in 1950", OWN, {"year_built": 1950}),
    ("Galvanized plumbing", OWN, {"plumbing_type": "Galvanized"}),
    ("Fuses", OWN, {"electrical": ["Fuses"]}),
    ("Fenced in-ground pool, boxes ticked", OWN, {"swimming_pool": "In Ground - Fenced", "pool_fence_4ft": True,
                                                   "pool_gate_locking": True}),
    ("Unfenced in-ground pool", OWN, {"swimming_pool": "In Ground - Unfenced"}),
    ("Pool with a diving board", OWN, {"swimming_pool": "In Ground - Fenced", "pool_accessories": "Diving board only"}),
    ("Rottweiler", OWN, {"has_dogs": "Yes", "dog_breeds": ["Rottweiler"]}),
    ("Solar panels, roof-mounted", OWN, {"solar_panels": "Yes", "solar_type": "Roof-mounted panels",
                                          "solar_tesla": "No"}),
    ("Owned by an LLC", OWN, {"ownership_type": "LLC"}),
    ("Family trust", OWN, {"ownership_type": "Trust", "trust_type": "Family trust"}),
    ("1 water loss in 2025", OWN, dict(L1, loss_types=["Water"])),
    ("1 fire loss in 2025", OWN, dict(L1, loss_types=["Fire"])),
    ("2 losses in 3 years (theft, wind)", OWN, dict(L1, losses_5yr="2", losses_3yr="2",
                                                     loss_types=["Theft", "Wind or hail"])),
    ("Seasonal home, primary with another carrier", OWN, {"occupancy_type": "Seasonal",
                                                           "primary_home_carrier": "Other carrier"}),
    ("Manufactured / mobile home", OWN, {"construction_type": "Manufactured/Mobile"}),
    ("A rental (tenant-occupied)", RENT, {}),
]
HOW = {"decided by a form field": "form", "gated-but-open": "confirm", "same rule as another row": "same as",
       "NONE": "not asked"}


def kind(m):
    if m["field"] == "NONE":
        return "NONE"
    if m["test"] == "always" and (m["map_note"] or "").startswith("decided by"):
        return "same rule as another row"
    return "gated-but-open" if "FACT(" in m["test"] else "decided by a form field"


def main(canon, out):
    wb = rv.CANON_TO_WB[canon]
    rules, fmap = rv._rules(), rv._map()
    rows = [rid for rid, m in fmap.items() if rules[rid]["Carrier"] == wb]
    lines = [f"# Review sheet: {display_names.display_name(canon)}", "",
             f"Program `{canon}` (table carrier \"{wb}\"), guide date {display_names.guide_date(canon) or '?'}. "
             f"{len(rows)} deciding rows. Reviewer: tick each row and each verdict, or write what the carrier really "
             "does.", "", "## The rows", "",
             "| Row | p. | Effect | How | When it applies | Rule | OK? |", "|---|---|---|---|---|---|---|"]
    for rid in rows:
        r, m = rules[rid], fmap[rid]
        gate = "every home" if m["gate"] in ("", "always") else f"`{m['gate'][:60]}`"
        lines.append(f"| {rid} | {rv._page(r)} | {m['outcome_if_fail']} | {HOW[kind(m)]} | {gate} | "
                     f"{r['Plain rule'][:110]} | |")
    lines += ["", "## The tool's verdict on standard homes", "",
              "| Home | Verdict | Deciding row / held on | Right? What the carrier really does |", "|---|---|---|---|"]
    for name, base, change in SCENARIOS:
        pd = dict(base, **change)
        if not rv.rules_table_wb(canon, set(rv.BATCHES), pd):
            lines.append(f"| {name} | not routed to this table | | |")
            continue
        out_ = rv.evaluate_carrier(canon, pd, wb=rv.rules_table_wb(canon, set(rv.BATCHES), pd))
        rec = rv.code_record(canon, out_, pd)[0]
        ids = re.findall(r"\[([A-Z][A-Z0-9]{2}-\d{3})\]", " ".join(rec["reasons"][:1]))
        opens = [rid for rid, (o, _) in out_.items() if o == "OPEN"]
        lines.append(f"| {name} | {cards.STATUS_LABEL.get(rec['status'], rec['status'])} | "
                     f"{', '.join(ids) or ', '.join(opens) or '-'} | |")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"{len(rows)} rows, {len(SCENARIOS)} homes -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
