"""The runtime data-defect detector (data_defects.py).

Brought to main from chat-tab (f5c496e, 0a7b120) so the eligibility pipeline
can use it; the chat tab's own refusal test stays with the chat tab. Runs
from the repo root, like the rest of the suite -- NO_TEXT detection reads
./carrier_eligibility_pdfs.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import data_defects


@pytest.mark.retrieval
class TestDataDefects:
    """The defect list must be derived, so it clears when the PDFs are fixed."""

    def test_the_two_mis_filed_programs_are_flagged(self):
        defects = data_defects.defective_programs()
        assert "Liberty_Mutual_HO6_-_02.21.2026" in defects
        assert "NatGen_Custom360_HO3_-_06.25.2026" in defects

    def test_the_correct_sibling_of_each_pair_is_NOT_flagged(self):
        """Flagging both halves of a duplicate pair would throw away a good
        guide with the bad one. DATA_DEFECTS.md establishes which is which:
        the Liberty Mutual file is the HO3 guide and the NatGen file is the
        DP3 landlord guide, so those two records are correct."""
        defects = data_defects.defective_programs()
        assert "Liberty_Mutual_HO3_-_02.21.2026" not in defects
        assert "NatGen_Custom360_DP3_-_06.25.2026" not in defects

    def test_centauri_ho3_is_flagged_as_having_no_readable_text(self):
        defect = data_defects.defective_programs().get("Centauri_-_HO3_-_05.01.2026")
        assert defect is not None
        assert defect["kind"] == data_defects.NO_TEXT

    def test_a_clean_program_is_not_flagged(self):
        """Guards against a detector that fires on everything."""
        defects = data_defects.defective_programs()
        assert "Allied_Trust_HO3" not in defects
        assert "Progressive_HO3_-_04.01.2026" not in defects

    def test_occidental_ho3_is_flagged_while_it_holds_the_dp3_guide(self):
        """DD-4: Sage_-_Occidental_HO3 holds Occidental's DWELLING FIRE PROGRAM
        (DP3) guide. Caught by the reference rule -- it names DP 00 03 / DP3
        five times and no HO product at all. Premise-guarded, so it clears
        itself once the real HO3 PDF is uploaded."""
        from shared_resources import get_vectorstore
        raw = get_vectorstore()._collection.get(
            where={"carrier": "Sage_-_Occidental_HO3"}, include=["documents"])
        if "DWELLING FIRE PROGRAM" not in " ".join(raw["documents"]).upper():
            pytest.skip("Sage_-_Occidental_HO3 no longer self-describes as DP3 -- DD-4 fixed?")
        defect = data_defects.defective_programs().get("Sage_-_Occidental_HO3")
        assert defect is not None and defect["kind"] == data_defects.WRONG_PRODUCT

    @pytest.mark.parametrize("program", [
        "Sage_-_Occidental_DP3",             # the CORRECT record of the DD-4 pair
        "Travelers_HO3_-_06.12.2026",        # a real LANDLORD section; 0 vs 0 references
        "Sage_-_Vave_HO3_-_07.01.2026",
        "Sage_-_Markel_HO3",
        "Liberty_Mutual_DP3_-_02.21.2026",   # 1 HO reference, a cross-reference
    ])
    def test_the_reference_rules_close_calls_are_not_flagged(self, program):
        """The reference rule must not over-block. Each of these was the
        nearest miss when its floor was set."""
        assert program not in data_defects.defective_programs()

    def test_exactly_the_four_known_defects_are_flagged(self):
        """DD-1 to DD-4 and nothing else. Anything new flagged is either a new
        mis-ingest (read the PDF) or a false positive (fix the rule)."""
        assert set(data_defects.defective_programs()) == {
            "NatGen_Custom360_HO3_-_06.25.2026",    # DD-1
            "Liberty_Mutual_HO6_-_02.21.2026",      # DD-2
            "Centauri_-_HO3_-_05.01.2026",          # DD-3
            "Sage_-_Occidental_HO3",                # DD-4
        }

    def test_guide_date_comes_from_the_filename(self):
        assert data_defects.guide_date("Progressive_HO3_-_04.01.2026") == "04.01.2026"
        assert data_defects.guide_date("Allied_Trust_HO3") is None
