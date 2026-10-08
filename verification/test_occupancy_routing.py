"""Round 29 step 4 (Liam's decision 2, 2026-10-08): Seasonal and Secondary Home (the
owner's own homes) are routed to HO3 programs as well as DP programs; each guide's
occupancy rows decide. Tenant Occupied and Vacant stay DP-only; HO6 unchanged. Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402

pytestmark = pytest.mark.retrieval


def _route(occupancy):
    return set(ec.get_carriers_for_occupancy(occupancy))


@pytest.mark.parametrize("occupancy", ["Seasonal", "Secondary Home"])
def test_an_owners_other_home_reaches_ho3_and_dp_programs(occupancy):
    got = _route(occupancy)
    owner, tenant = _route("Owner Occupied"), _route("Tenant Occupied")
    ho3 = {c for c in owner if ec.carrier_programs(c)[0] and not ec._is_condo_program(c)}
    assert ho3 and ho3 <= got                                   # every HO3 program the owner's home gets
    assert tenant <= got                                        # and every DP program
    assert not any(ec._is_condo_program(c) for c in got - tenant)  # HO6 routing unchanged


@pytest.mark.parametrize("occupancy", ["Tenant Occupied", "Vacant"])
def test_tenant_and_vacant_stay_dp_only(occupancy):
    got = _route(occupancy)
    combined = set(ec.get_combined_program_carriers())
    assert not any(ec.carrier_programs(c)[0] and c not in combined for c in got)


def test_owner_occupied_is_unchanged():
    assert not any(ec.carrier_programs(c)[1] and c not in set(ec.get_combined_program_carriers())
                   for c in _route("Owner Occupied"))


def test_the_system_prompt_names_tenant_and_vacant_only():
    assert "Tenant Occupied or any non-owner occupancy" not in ec.SYSTEM_INSTRUCTIONS
    assert "Seasonal or Secondary Home (the owner's own second home)" in ec.SYSTEM_INSTRUCTIONS
