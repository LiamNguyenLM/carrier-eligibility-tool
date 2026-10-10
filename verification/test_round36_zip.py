"""Round 36 step 3 (Liam, 2026-10-10): his check used ZIP 77248, a Houston PO-box ZIP the Census ZIP table does
not have, and County was left blank. A ZIP missing from the table now looks at the table ZIPs sharing its first
three digits: when one county holds at least 90% of their summed shares, County is pre-filled with it and the
form says so; otherwise County stays blank and the form asks for the street ZIP. 12 of the 49 Texas prefixes
in the table resolve. Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402
import intake_fields  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


def test_liams_zip_is_checked_as_harris_with_his_wording():
    assert intake_fields.county_for_zip("77248") == (
        "Harris", "ZIP 77248 isn't a street ZIP (it may be a PO box). Checked as Harris County; change County if "
                  "the home is elsewhere.")


@pytest.mark.parametrize("zip5,county", [("77001", "Harris"), ("76101", "Tarrant"), ("78711", "Travis"),
                                         ("75221", "Dallas"), ("78295", "Bexar"), ("79105", None)])
def test_other_missing_zips_take_their_prefixs_county(zip5, county):
    assert zip5 not in intake_fields.ZIP_COUNTIES
    got, msg = intake_fields.county_for_zip(zip5)
    if county is None:                                   # prefix 791 (Amarillo) is split: no 90% county
        assert got == "" and msg.endswith("Use the property's street ZIP.")
    else:
        assert got == county and msg.startswith(f"ZIP {zip5} isn't a street ZIP") and f"as {county} County" in msg


@pytest.mark.parametrize("zip5", ["75099", "76099"])
def test_a_missing_zip_in_a_split_prefix_stays_blank_and_asks_for_the_street_zip(zip5):
    county, msg = intake_fields.county_for_zip(zip5)
    assert county == ""
    assert msg == (f"ZIP {zip5} is not in the ZIP-to-county table (PO-box-only and some special ZIPs are "
                   "missing), so County is left blank. Use the property's street ZIP.")


def test_how_many_texas_prefixes_resolve():
    prefixes = {z[:3] for z in intake_fields.ZIP_COUNTIES}
    texas = {p for p in prefixes if intake_fields.is_texas_zip_range(p + "00") or intake_fields.is_texas_zip_range(p + "99")}
    resolved = {p for p in texas if p in intake_fields.PREFIX_COUNTIES}
    assert (len(texas), len(resolved)) == (49, 12)
    assert all(share >= 0.90 for _, share in intake_fields.PREFIX_COUNTIES.values())


def test_a_zip_in_the_table_and_a_non_texas_zip_are_unchanged():
    assert intake_fields.county_for_zip("77002") == ("Harris", "Checked as Harris County (from ZIP 77002).")
    assert intake_fields.county_for_zip("76801")[0] == "Brown"
    assert intake_fields.county_for_zip("90210") == ("", "ZIP 90210 is not a Texas ZIP, so County is left blank.")


def test_the_form_prefills_harris_from_77248_and_says_so(monkeypatch):
    from streamlit.testing.v1 import AppTest
    calls = []
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: calls.append((pd, kw)) or [])
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.text_input(key="zip").input("77248").run()
    assert not at.exception
    assert at.selectbox(key="county").value == "Harris"
    assert at.checkbox(key="chk_county").value is True
    assert any("ZIP 77248 isn't a street ZIP (it may be a PO box). Checked as Harris County" in c.value
               for c in at.caption)
    at.selectbox(key="dwelling_type").select("House").run()
    at.button(key="submit").click().run()
    pd, kw = calls[-1]
    assert pd["county"] == "Harris" and "county" in kw["checked_topics"]


def test_the_agent_can_still_change_the_prefilled_county(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: [])
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.text_input(key="zip").input("77248").run()
    at.selectbox(key="county").select("Fort Bend").run()
    assert at.selectbox(key="county").value == "Fort Bend"
    assert any("set by hand; ZIP 77248 suggests Harris" in c.value for c in at.caption)
