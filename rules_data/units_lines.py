"""Round 39 step 4 (Liam): the rows decided by the form's optional "Units in the building" (asked for a House:
1 / 2 / 3-4 / 5 or more / Unknown). Shared by the five map builders: each REPLACES its own line for a row here (these
rows were NONE, a FACT, or decided on the dwelling type alone). Blank or Unknown is a confirm, never a hold
(rules_evaluator.CONFIRM_FIELDS). A Townhome or Condo is not asked: these lines read only a House (a townhome is one
unit; a condo has its own rows).

Not decided here (the count alone does not settle them): tenants per unit (ODP-036, SDP-022, FDP-040), the total of
rentals an owner has (SAG-012 / SUR-029 / SFP-029 / WIL-030 / TRI-009), whether every unit has a full-time renter
(SAG-015 / SUR-034 / SFP-034 / WIL-037 / TRI-017 / LDP-007), multi-family zoning and alarms (NCD-045 / NCD-050), the
high-value single-family programs (CDP-094, PDP-008) and NatGen Premier Dwelling Fire (NPD-013..015: closed).
"""

HOUSE = "dwelling_type == House"
SINGLE = "units_in_building in {1}"
ONE_OR_TWO = "units_in_building in {1, 2}"
ONE_TO_FOUR = "units_in_building not in {5 or more}"
F = "dwelling_type;units_in_building"
NOTE = "round 39 step 4: the form's 'Units in the building' (a House); blank or Unknown is a confirm"
SEASONAL = "occupancy_type in {Seasonal, Secondary Home}"


def _single_or_townhome(gate, note=NOTE):
    # "single-family dwellings or single townhouse units": a townhome passes; a house passes with 1 unit
    return (F, "dwelling_type in {House, Townhome} and (dwelling_type == Townhome or " + SINGLE + ")", gate, "", note)


LINES = {
    # Allied: "Multi-family structures and any building other than a single-family dwelling or single townhouse unit
    # are ineligible" (ALL-019, the same fact worded as a permission, keeps its line)
    "ALL-020": _single_or_townhome("always"),
    # Sage: "Seasonal or secondary residences must be single family"
    **{rid: ("occupancy_type;" + F, "dwelling_type in {House, Townhome} and (dwelling_type == Townhome or " + SINGLE
             + ")", SEASONAL, "", NOTE)
       for rid in ("SAG-003", "SUR-016", "SFP-016", "WIL-016", "TRI-004")},
    # one-to-four family dwellings
    **{rid: (F, ONE_TO_FOUR, HOUSE, "", NOTE)
       for rid in ("SAG-020", "SUR-005", "SFP-005", "WIL-005", "TRI-026", "LIB-008", "LDP-023", "STD-036")},
    # one- or two-family dwellings
    **{rid: (F, ONE_OR_TWO, HOUSE, "", NOTE) for rid in ("MER-008", "SLL-040", "CHO-014")},
    # The Hartford: an owner's home (HAR-033) and a rental (HAR-071, RPP+) -- 1 or 2 families
    "HAR-033": ("occupancy_type;" + F, ONE_OR_TWO, HOUSE + " and occupancy_type != Tenant Occupied", "", NOTE),
    "HAR-071": ("occupancy_type;" + F, ONE_OR_TWO, HOUSE + " and occupancy_type == Tenant Occupied", "", NOTE),
    # ARI: "Townhomes and duplexes are ineligible unless they meet the Single Building definition" -- a 2-unit house
    # is a duplex: the same confirm a townhome gets
    **{rid: (F, "FACT(meets the Single Building definition)", "dwelling_type == Townhome or (" + HOUSE + " and "
             "units_in_building in {2})", "Single Building definition", NOTE) for rid in ("ARA-011", "ARB-009")},
}
