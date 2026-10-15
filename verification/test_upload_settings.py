"""Round 39 steps 2c / 2d (Liam): a carrier added by upload -- zero API, on The Hartford's guide
(verification/fixtures/The_Hartford_HO3_-_07.09.2026.pdf), uploaded under the name Liam's Railway upload had.

2c  the guide date comes from the guide's text (header, page 1, last page), then the file name; the upload and the card
    say which was used: "The Hartford HO3 10.12.2026" is dated 07/09/2026 from its header.
2d  the upload asks the display name (pre-filled), the forms written and the occupancies offered; the check routes and
    names the program by them (the stand-in store: nothing reaches carrier_docs_db)."""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import cards  # noqa: E402
import display_names  # noqa: E402
import eligibility_check as ec  # noqa: E402
import pdf_extraction as pe  # noqa: E402
import rules_evaluator as rv  # noqa: E402
import store_cache  # noqa: E402
import upload_carrier  # noqa: E402
from test_held_reasons import HOME, LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
PDF = os.path.join(HERE, "fixtures", "The_Hartford_HO3_-_07.09.2026.pdf")
RAILWAY_NAME = "The Hartford HO3 10.12.2026"
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


# ---- 2c: the guide date
@pytest.fixture(scope="module")
def pages():
    return pe.load_upload_documents(PDF)[0]


def test_the_date_comes_from_the_guides_header_not_the_file_name(pages):
    date, source = upload_carrier.guide_date_for_upload(pages, RAILWAY_NAME)
    assert date == "07/09/2026" and source.startswith("the guide's text (header")
    assert "Effective Date: 07/09/2026" in source


@pytest.mark.parametrize("text,want", [("Underwriting Guidelines  REVISED 2/24/26", "02/24/2026"),
                                       ("Homeowners Program  Effective 11/16/22", "11/16/2022"),
                                       ("Edition Date: 08/01/2024", "08/01/2024")])
def test_other_ways_a_guide_states_its_date(text, want):
    from langchain_core.documents import Document
    assert pe.guide_date_from_docs([Document(page_content=text, metadata={"page": 0})])[0] == want


def test_without_a_date_in_the_text_the_file_name_is_used_and_said():
    from langchain_core.documents import Document
    docs = [Document(page_content="no date here", metadata={"page": 0})]
    assert upload_carrier.guide_date_for_upload(docs, "Acme_HO3_-_03.01.2026") == ("03/01/2026", "the file name")
    assert upload_carrier.guide_date_for_upload(docs, "Acme HO3") == ("", "")


def test_the_card_names_where_the_date_came_from():
    assert display_names.guide_line("X", "07/09/2026", "the guide's text (header: \"Effective Date: 07/09/2026\")") \
        == "Guide date: 07/09/2026 (from the guide's text (header: \"Effective Date: 07/09/2026\"))"
    assert display_names.guide_line("Travelers_HO3_-_06.12.2026") == "Guide date: 06/12/2026"     # the seed: as before


# ---- 2d: the upload's settings, stored on every chunk
class FakeStore:
    def __init__(self):
        self.rows = []

        class Coll:
            def get(_, include=None, where=None, **k):
                return {"metadatas": [m for _, m in self.rows], "documents": [d for d, _ in self.rows],
                        "ids": [str(i) for i in range(len(self.rows))]}
        self._collection = Coll()

    def add_documents(self, batch):
        self.rows.extend((d.page_content, dict(d.metadata)) for d in batch)


@pytest.fixture
def uploaded(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(upload_carrier, "get_vectorstore", lambda: store)
    n, err = upload_carrier.add_carrier_to_database(open(PDF, "rb").read(), RAILWAY_NAME, settings={
        "display_name": "The Hartford (HO3)", "forms": ["HO3"],
        "occupancies": ["Owner Occupied", "Tenant Occupied", "Seasonal", "Secondary Home"]})
    assert err is None and n > 30
    return store


def test_every_chunk_carries_the_settings_and_the_date(uploaded):
    metas = [m for _, m in uploaded.rows]
    assert all(m["display_name"] == "The Hartford (HO3)" and m["forms"] == "HO3" for m in metas)
    assert all(m["occupancies"] == "Owner Occupied, Tenant Occupied, Seasonal, Secondary Home" for m in metas)
    assert all(m["guide_date"] == "07/09/2026" and "header" in m["guide_date_source"] for m in metas)
    assert upload_carrier.LAST_UPLOAD["guide_date"] == "07/09/2026"
    assert not any("MVR" in d or "MAAA" in d for d, _ in uploaded.rows)          # 2b: no hidden auto text


def test_an_upload_without_settings_stores_only_the_date(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(upload_carrier, "get_vectorstore", lambda: store)
    upload_carrier.add_carrier_to_database(open(PDF, "rb").read(), RAILWAY_NAME)
    assert all("forms" not in m and m["guide_date"] == "07/09/2026" for _, m in store.rows)


def test_default_occupancies_follow_the_forms():
    assert upload_carrier.default_occupancies(["HO3"]) == ["Owner Occupied", "Seasonal", "Secondary Home"]
    assert upload_carrier.default_occupancies(["DP3"]) == ["Tenant Occupied", "Seasonal", "Vacant", "Secondary Home"]


SETTINGS = {RAILWAY_NAME: {"display_name": "The Hartford (HO3)", "forms": "HO3",
                           "occupancies": "Owner Occupied, Tenant Occupied", "guide_date": "07/09/2026",
                           "guide_date_source": "the guide's text (header: \"New Business Effective Date: 07/09/2026\")"}}


@pytest.mark.parametrize("occupancy,routed", [("Owner Occupied", True), ("Tenant Occupied", True),
                                              ("Seasonal", False), ("Vacant", False)])
def test_routing_follows_the_occupancies_offered(monkeypatch, occupancy, routed):
    monkeypatch.setattr(ec, "upload_settings", lambda: SETTINGS)
    assert ec._fits_occupancy(RAILWAY_NAME, occupancy, set()) == routed
    assert ec.carrier_programs(RAILWAY_NAME) == (True, False)


def test_a_seed_program_without_settings_routes_as_before(monkeypatch):
    monkeypatch.setattr(ec, "upload_settings", lambda: SETTINGS)
    assert not ec._fits_occupancy("Travelers_HO3_-_06.12.2026", "Tenant Occupied", set())


def test_upload_settings_reads_the_store(monkeypatch):
    raw = {"metadatas": [{"carrier": RAILWAY_NAME, "lob": "HO3", **SETTINGS[RAILWAY_NAME]},
                         {"carrier": "Other_HO3", "lob": "HO3"}, None]}
    monkeypatch.setattr(store_cache, "derived", lambda name, coll, compute, documents=False: compute(raw))
    assert ec.upload_settings() == {RAILWAY_NAME: SETTINGS[RAILWAY_NAME]}


def test_the_seed_has_no_upload_settings():
    """Every guide in the seed was indexed without settings: routing and names are unchanged for all of them."""
    assert ec.upload_settings() == {}
