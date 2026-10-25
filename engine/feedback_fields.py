"""Round 43 step 1: the parts of a "This looks wrong" report the browser fills itself -- the choices and the
deciding rows (moved from feedback.py, which imports them from here)."""
import re

CHOICES = ("Should be Eligible", "Should be Ineligible", "Should be Refer", "Not sure")
# Round 40 step 2: NatGen Custom360 HO3's rows are NC3-NNN and Progressive HO6's PH6-NNN (a digit in the prefix);
# they were missing from deciding_rows
ROW_ID = re.compile(r"\b[A-Z][A-Z0-9]{2}-\d{3}\b")


def deciding_rows(record):
    """The rules-table rows the card rests on: every row ID in its reasons, citations, missing items and
    notes, in order of first appearance."""
    seen = []
    for field in ("reasons", "citations", "missing_info", "also_confirm"):
        for text in record.get(field) or []:
            for rid in ROW_ID.findall(str(text)):
                if rid not in seen:
                    seen.append(rid)
    for rid in ROW_ID.findall(str(record.get("notes") or "")):
        if rid not in seen:
            seen.append(rid)
    return seen
