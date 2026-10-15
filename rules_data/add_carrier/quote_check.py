"""Add a carrier, step 3c (pilot_structured_rules/ADD_CARRIER.md): Rule IDs and the two quote checks
(EXTRACTION_SPEC_v2.md, "Quotes"), from the extractor's rows.json to the rules CSV the app reads.

usage: python rules_data/add_carrier/quote_check.py <rows.json> <work folder> <PREFIX> "<workbook carrier name>"
                                                    <guide file name> <out.csv>
  rows.json        the extractor's rows (EXTRACT_TASK.md fields), in guide order; after review fixes
  work folder      prepare_guide.py's (reading_order.txt, layout.txt)
  PREFIX           3 capital letters, unused by any other table (rules_evaluator._rules())
Each row gets PREFIX-001.. in order. "Quote in PDF text": letters and digits found on the stated page (reading order
or layout). "Quote in app stored text": found anywhere in the stored text (what the app's store holds). A FAIL needs a
reason in "Quote check note" before the table is used; the script prints every FAIL.
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import quotes  # noqa: E402

COLUMNS = ["Rule ID", "Carrier", "Topic", "State", "Effect", "Plain rule", "Check type", "Value", "Unit",
           "Applies when", "Exceptions / cure", "Verbatim quote from guide", "PDF page", "Quote in PDF text",
           "Confidence", "Review note", "Source file", "Tool handling", "Also topic", "Quote in app stored text",
           "Quote check note"]
FIELDS = {"Topic": "topic", "State": "state", "Effect": "effect", "Plain rule": "plain_rule",
          "Check type": "check_type", "Value": "value", "Unit": "unit", "Applies when": "applies_when",
          "Exceptions / cure": "exceptions", "Verbatim quote from guide": "quote", "PDF page": "page",
          "Confidence": "confidence", "Review note": "review_note", "Tool handling": "tool_handling",
          "Also topic": "also_topic"}


def pages(path):
    text = open(path, encoding="utf-8").read()
    parts = re.split(r"=====PAGE (\d+)=====\n", text)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def found(quote, text):
    q = quotes.compare_key(quote)
    return bool(q) and quotes.appears_in(q, quotes.compare_key(text))


def main(rows_json, work, prefix, carrier, source_file, out):
    assert re.fullmatch(r"[A-Z]{3}", prefix), "PREFIX: 3 capital letters"
    rows = json.load(open(rows_json, encoding="utf-8"))
    ro, lay = pages(os.path.join(work, "reading_order.txt")), pages(os.path.join(work, "layout.txt"))
    stored = "\n".join(ro.values())
    out_rows, fails = [], []
    for i, r in enumerate(rows, 1):
        rec = {c: "" for c in COLUMNS}
        rec.update({c: str(r.get(f, "") if r.get(f) is not None else "") for c, f in FIELDS.items()})
        rec.update({"Rule ID": f"{prefix}-{i:03d}", "Carrier": carrier, "Source file": source_file,
                    "Quote check note": r.get("quote_check_note", "")})
        q = rec["Verbatim quote from guide"]
        if rec["State"] == "SILENT" or not q:
            rec["Quote in PDF text"] = rec["Quote in app stored text"] = "N/A"
        else:
            try:
                page = int(float(rec["PDF page"]))
            except ValueError:
                page = None
            rec["Quote in PDF text"] = "PASS" if page and (found(q, ro.get(page, "")) or found(q, lay.get(page, ""))) \
                else "FAIL"
            rec["Quote in app stored text"] = "PASS" if found(q, stored) else "FAIL"
            if "FAIL" in (rec["Quote in PDF text"], rec["Quote in app stored text"]) and not rec["Quote check note"]:
                fails.append(f"{rec['Rule ID']} p.{rec['PDF page']}: {q[:80]}")
        out_rows.append(rec)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"# source: {os.path.basename(rows_json)} ({carrier}), quote-checked by "
                 f"rules_data/add_carrier/quote_check.py\n")
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)
    print(f"{len(out_rows)} rows -> {out}; quote FAILs without a note: {len(fails)}")
    for f in fails:
        print("  FAIL", f)
    return fails


if __name__ == "__main__":
    sys.exit(1 if main(*sys.argv[1:7]) else 0)
