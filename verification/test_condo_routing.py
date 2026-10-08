"""Round 30 step 4 (Liam, 2026-10-08, decision 4): condo units that are tenant-occupied, seasonal or
secondary go to Progressive HO6 as well; its rows decide. Vacant condo units are not routed
(PH6-012). Every non-condo profile is unchanged. Zero API.

Scope of the HO6 occupancy rows (Progressive HO6 guide, p.2):
  "OWNER-OCCUPIED CONDOMINIUM UNIT / An owner-occupied condominium unit must be:"
      PH6-013 "Occupied by the insured and the insured's immediate family. No roomers or boarders"
      PH6-017 "Occupied for a minimum of three months per year to be eligible for this program."
  "RENTER-OCCUPIED CONDOMINIUM UNIT"
      PH6-018 "Condominium units must be rented on leases with minimum terms of one week."
      PH6-021 "Condominium units occupied less than three months per year are considered ineligible."
None of them is mapped to decline a tenant: PH6-013 and PH6-021 are NONE (lease and months are not
asked), PH6-017 is gated to Seasonal / Secondary Home."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
import rules_evaluator as ev  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval
PH6, LIB6 = "Progressive_HO6_-_10.01.2025", "Liberty_Mutual_HO6_-_02.21.2026"
USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
CONDO = dict(STANDARD_PROFILE, dwelling_type="Condo", county="Bexar", swimming_pool="No Pool")


def _run(pd):
    prompts = []

    def fake(system, user, max_tokens):
        prompts.append(user)
        names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if "RULE CHECK:" in user
                 else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    saved = ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH
    ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH = \
        fake, True, True, True, True
    try:
        return {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}
    finally:
        ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH = saved


@pytest.mark.parametrize("occupancy", ["Tenant Occupied", "Seasonal", "Secondary Home"])
def test_a_non_owner_condo_unit_reaches_progressive_ho6(occupancy):
    res = _run(dict(CONDO, occupancy_type=occupancy))
    assert PH6 in res and res[PH6].get("rules_table")
    assert LIB6 not in res                     # its file is the HO3 guide (DD-1): nothing to quote


@pytest.mark.parametrize("pd", [dict(CONDO, occupancy_type="Vacant"),                     # PH6-012
                                dict(CONDO, occupancy_type="Tenant Occupied", dwelling_type="House"),
                                dict(CONDO, occupancy_type="Tenant Occupied", dwelling_type="Townhome")])
def test_vacant_condos_and_other_dwellings_are_not_routed_to_ho6(pd):
    assert PH6 not in _run(pd)


def test_a_tenant_occupied_condo_with_a_one_year_lease_is_not_declined_by_the_owner_occupied_rows():
    # correction 4: PH6-013 / PH6-017 sit under OWNER-OCCUPIED, PH6-021 is the renter row on months
    pd = dict(CONDO, occupancy_type="Tenant Occupied")
    out = ev.evaluate_carrier(PH6, pd)
    for rid in ("PH6-013", "PH6-017", "PH6-021", "PH6-018"):
        if rid in out:
            assert out[rid][0] not in ("FAIL", "OPEN"), (rid, out[rid])
    card = _run(pd)[PH6]
    assert card["status"] != "INELIGIBLE", card["reasons"]
    assert not any(re.search(r"\[PH6-0(13|17|21)\]", x) for x in card["reasons"] + card.get("missing_info", []))


def test_the_three_month_row_applies_to_a_seasonal_unit_as_a_confirm_note():
    out = ev.evaluate_carrier(PH6, dict(CONDO, occupancy_type="Seasonal"))
    assert out["PH6-017"][0] == "NOTE"         # months occupied are not asked (round 30 step 2)


def test_owner_occupied_condos_route_as_before():
    assert ec._condo_unit_fits(PH6, "Owner Occupied", CONDO) is False      # already routed by occupancy
    assert PH6 in ec.get_carriers_for_occupancy("Owner Occupied")
