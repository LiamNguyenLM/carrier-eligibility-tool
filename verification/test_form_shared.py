"""Round 43 step 2 (Liam, 2026-10-24): app.py and the static page share one form -- engine/form.py holds its choice
lists, texts and form_request (the property_details a submit builds), and app.py reads them from there. These tests
keep the refactor honest and the two forms together:
- four fillings of app.py's form (the ZIP prefill and a Harris home; a rental with an LLC, losses, electrical, units
  and an amount; a seasonal trust home with solar, a fenced pool and dogs; a condo with the county set by hand and
  every topic ticked) send exactly what the app sent BEFORE the refactor (recorded from 750f005 in
  fixtures/form_fillings_round43.json);
- app.py no longer hard-codes the lists engine.form holds; the page's spec takes intake_fields' lists. Zero API."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
import eligibility_check as ec  # noqa: E402
import intake_fields as I  # noqa: E402
from engine import form  # noqa: E402

APP = os.path.join(ROOT, "app.py")
RECORDED = os.path.join(HERE, "fixtures", "form_fillings_round43.json")
FILLINGS = {
    "harris_owner": [("text_input", "zip", "77248"), ("selectbox", "ppc", "5"), ("selectbox", "hydrant", "Yes"),
                     ("number_input", "year", 1994), ("selectbox", "plumbing", "Copper"),
                     ("selectbox", "dwelling_type", "House"), ("checkbox", "chk_roof_age", True)],
    "rental_llc_losses": [("selectbox", "occupancy", "Tenant Occupied"), ("radio", "ownership", "LLC"),
                          ("selectbox", "owner_home_carrier", "The Hartford"), ("selectbox", "rental_units", "1-4"),
                          ("selectbox", "rental_term", "Long-term"), ("selectbox", "dwelling_type", "House"),
                          ("selectbox", "units_in_building", "2"), ("selectbox", "losses_5yr", "2"),
                          ("multiselect", "loss_types", ["Water", "Wind or hail"]), ("number_input", "loss_year", 2024),
                          ("selectbox", "losses_3yr", "1"), ("multiselect", "electrical", ["Circuit breakers"]),
                          ("text_input", "dwelling_amount", "450,000"), ("text_input", "station_miles", "3.5")],
    "seasonal_trust_solar_pool": [("selectbox", "occupancy", "Seasonal"), ("radio", "ownership", "Trust"),
                                  ("selectbox", "trust_type", "Family trust"),
                                  ("selectbox", "primary_carrier", "Travelers"), ("text_input", "primary_miles", "40"),
                                  ("toggle", "solar", True), ("selectbox", "solar_type", "Roof-mounted panels"),
                                  ("selectbox", "solar_tesla", "No"), ("selectbox", "pool", "In Ground - Fenced"),
                                  ("selectbox", "poolacc", "Slide only"),
                                  ("checkbox", "pool_fence_4ft::In Ground - Fenced", True),
                                  ("selectbox", "coastal", "Tier 2 - Moderate coastal area"),
                                  ("selectbox", "dwelling_type", "Townhome"), ("toggle", "dogs", True),
                                  ("multiselect", "dog_breeds", ["None of these"])],
    "condo_county_by_hand": [("text_input", "zip", "78701"), ("selectbox", "county", "Bexar"),
                             ("selectbox", "dwelling_type", "Condo"), ("selectbox", "rooftype", "Tile"),
                             ("selectbox", "roofshape", "Flat"), ("selectbox", "construction", "Masonry"),
                             ("number_input", "roofage", 22), ("button", "select_all", None)],
}


def _fill(monkeypatch, steps):
    from streamlit.testing.v1 import AppTest
    calls = []
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: calls.append([pd, kw.get("checked_topics")]) or [])
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["authenticated"] = True
    at.run()
    for kind, key, value in steps:
        w = getattr(at, kind)(key=key)
        if kind == "button":
            w.click().run()
        elif kind == "toggle":
            w.set_value(value).run()
        elif kind == "checkbox":
            (w.check() if value else w.uncheck()).run()
        elif kind == "multiselect":
            for v in value:
                w = at.multiselect(key=key).select(v)
            w.run()
        elif kind == "text_input":
            w.input(value).run()
        elif kind == "number_input":
            w.set_value(value).run()
        else:
            (w.set_value(value) if kind == "radio" else w.select(value)).run()
        assert not at.exception, (key, at.exception)
    at.button(key="submit").click().run()
    assert not at.exception, at.exception
    return json.loads(json.dumps(calls[-1], default=str))


@pytest.mark.parametrize("name", list(FILLINGS))
def test_the_form_sends_what_it_sent_before_the_refactor(monkeypatch, name):
    with open(RECORDED, encoding="utf-8") as fh:
        recorded = json.load(fh)[name]
    assert _fill(monkeypatch, FILLINGS[name]) == recorded


def test_app_py_reads_the_form_lists_from_the_engine():
    src = open(APP, encoding="utf-8").read()
    for literal in ('"Tier 1 - Closest to coast"', '"Masonry Veneer"', '"Gambrel"', '"Above Ground - Unfenced"',
                    '"Both slide and diving board"', "max_value=2026"):
        assert literal not in src, literal
    assert "engine_form.form_request(" in src and "engine_form.VALUE_KEYS" in src


def test_the_spec_takes_the_engines_lists_and_strings():
    spec = {f["key"]: f for f in form.form_spec()["fields"]}
    assert spec["ppc"]["choices"] == list(I.PPC_CHOICES) and spec["rooftype"]["choices"] == list(I.ROOF_TYPES)
    assert spec["coastal"]["choices"] == list(form.COASTAL_CHOICES)
    assert form.FALLBACK_LINE == ec.FALLBACK_LINE
    assert set(form.VALUE_KEYS) | {"pool_fence_4ft", "pool_gate_locking"} == set(spec)


@pytest.mark.parametrize("key,text,field", [("station_miles", "9", "fire_station_miles"),
                                            ("primary_miles", "40", "primary_home_miles")])
def test_the_forms_json_keeps_a_whole_number_distance_a_float(key, text, field):
    """Round 43 step 2 (found by the browser harness: 726 card-text differences in 71 profiles): JavaScript turns 9.0
    into 9, and a card then read "Fire station 9 mi" where the app reads "9.0 mi". The page passes form_request's
    JSON text to check_json untouched, so the float survives."""
    values = {"dwelling_type": "House", "occupancy": "Seasonal", "pool": "No Pool", "year": 2000, "roofage": 10,
              "coastal": "Not Coastal", "dogs": False, "solar": False, "chk": {}, key: text}
    req = form.form_request(values)
    assert isinstance(json.loads(req["property_details_json"])[field], float)
    assert json.loads(req["property_details_json"]) == req["property_details"]


def test_check_json_reads_the_text_as_python_wrote_it(monkeypatch):
    from engine import api
    import engine.pipeline as pipeline
    for f in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(pipeline, f, True)
    pd = {"year_built": 1995, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
          "construction_type": "Frame", "plumbing_type": "PVC", "pool_accessories": "None",
          "occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner",
          "coastal_tier": "Not Coastal", "swimming_pool": "No Pool", "has_dogs": "No", "dog_breeds": [],
          "solar_panels": "No", "ppc": "10", "fire_station_miles": 9.0, "hydrant_1000ft": "Unknown", "zip": "",
          "county": "Travis", "dwelling_amount": None, "dwelling_type": "House"}
    page = api.check_json(json.dumps(pd))
    text = json.dumps([c["first"] for c in page["cards"]])
    assert "Fire station 9.0 mi" in text and "Fire station 9 mi" not in text
