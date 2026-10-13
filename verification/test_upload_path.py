"""Round 39 steps 2a/2b: the upload path (pdf_extraction.load_upload_documents), zero API, on The Hartford HO3 guide.

Liam's run went wrong on the Hartford because (1) page 1 carries ~1,300 characters of an auto guide drawn in blue,
stacked on one line, plus off-page text -- invisible on the page, but read by pdfplumber; and (2) "Swimming pool"
under Rental Property Protection Plus (p.6) was read without its heading, so a homeowners pool was declined from the
RPP+ section. The upload path drops text that is not drawn on the rendered page and gives every chunk its section."""
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import pdf_extraction as pe  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

pytestmark = pytest.mark.retrieval
PDF = os.path.join(HERE, "fixtures", "The_Hartford_HO3_-_07.09.2026.pdf")
AUTO_WORDS = ("MVR", "Vehicle", "PIP", "Accidents", "Violations", "driver")


@pytest.fixture(scope="module")
def upload():
    return pe.load_upload_documents(PDF)


@pytest.fixture(scope="module")
def chunks(upload):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=75)
    return pe.section_prefixed(pe.chunk_documents(upload[0], splitter))


def _section(docs, name):
    return [d for d in docs if d.metadata.get("section") == name]


# ---- 2b: hidden text
def _garbled(text):
    """The stacked hidden text reads as one run of interleaved letters ("MAAA\"ALYSBcnnCeceLNercnn...")."""
    return "MAAA" in text or any(len(w) >= 40 for w in text.split())


def test_the_hidden_auto_guide_is_dropped(upload):
    docs, dropped = upload
    assert dropped > 1000
    text = "\n".join(d.page_content for d in docs)
    assert not _garbled(text)
    for w in AUTO_WORDS:
        assert w not in text, w


def test_the_old_path_did_read_the_hidden_text():
    """The fixture still holds the hidden text (so the test above is not vacuous): the old path reads it, garbled."""
    assert _garbled(pe.load_pdf_as_documents(PDF)[0].page_content)


def test_visible_text_is_kept(upload):
    text = "\n".join(d.page_content for d in upload[0])
    for phrase in ("Primary home not insured with The Hartford", "Unfenced inground swimming pool",
                   "Central fire and burglar alarm", "knob & tube"):
        assert phrase.lower() in text.lower(), phrase


# ---- 2a: sections
def test_the_guide_header_is_kept_once_with_the_effective_date(upload):
    header = _section(upload[0], "Guide header")
    assert len(header) == 1 and "Effective Date: 07/09/2026" in header[0].page_content
    assert sum("New Business Effective Date" in d.page_content for d in upload[0]) == 1


@pytest.mark.parametrize("name", ["Rental Property Protection Plus", "High Value Homes ($1,500,000+)", "Losses",
                                  "Unfenced inground swimming pool", "Secondary/Seasonal Residence", "Roof"])
def test_named_sections(upload, name):
    assert _section(upload[0], name), [d.metadata["section"] for d in upload[0]]


def test_the_rpp_pool_line_carries_its_section(chunks):
    pool = [c for c in chunks if "swimming pool" in c.page_content.lower() and c.metadata["page"] == 5]
    assert pool and all(c.page_content.startswith("[Rental Property Protection Plus]") for c in pool)


def test_the_homeowners_pool_line_is_its_own_section(chunks):
    pool = [c for c in chunks if c.metadata["page"] == 7 and "Unfenced inground swimming pool" in c.page_content]
    assert pool and all(c.page_content.startswith("[Unfenced inground swimming pool]") for c in pool)
    assert not any("Rental Property" in c.page_content for c in pool)


def test_the_alarm_line_carries_the_high_value_heading(chunks):
    alarm = [c for c in chunks if "central fire and burglar alarm" in c.page_content.lower()]
    assert alarm and all(c.page_content.startswith("[High Value Homes ($1,500,000+)]") for c in alarm)


@pytest.mark.parametrize("line,heading", [
    ("Unfenced inground swimming pool Decline", "Unfenced inground swimming pool"),
    ("Customer with outstanding earned premium Refer to Underwriting", "Customer with outstanding earned premium")])
def test_a_condition_with_its_action_on_one_line_is_a_section(upload, line, heading):
    assert any(d.metadata["section"] == heading and line.split()[0] in d.page_content for d in upload[0])


def test_every_split_chunk_starts_with_its_section(chunks):
    multi = [c for c in chunks if c.metadata.get("section")]
    assert len(multi) > 35
    assert all(c.page_content.startswith(f"[{c.metadata['section']}]") for c in multi)


def test_section_prefixed_is_a_no_op_without_sections():
    from langchain_core.documents import Document
    d = Document(page_content="plain text", metadata={"page": 0, "is_table": False})
    assert pe.section_prefixed([d])[0].page_content == "plain text"


# ---- existing guides are unchanged: the upload path applies to files named in UPLOAD_PATH_FILES and to new uploads
def test_a_guide_not_listed_reads_exactly_as_before(tmp_path):
    other = tmp_path / "Some_Other_Carrier_HO3.pdf"
    shutil.copy(PDF, other)
    docs, source = pe.load_guide_documents(str(other))
    old = pe.load_pdf_as_documents(str(other))
    assert source == "pdf" and [d.page_content for d in docs] == [d.page_content for d in old]


def test_only_the_hartford_is_listed():
    assert pe.UPLOAD_PATH_FILES == {"The_Hartford_HO3_-_07.09.2026.pdf"}


def test_the_listed_hartford_takes_the_upload_path():
    docs, source = pe.load_guide_documents(PDF)
    assert source.startswith("pdf (upload path") and _section(docs, "Rental Property Protection Plus")
