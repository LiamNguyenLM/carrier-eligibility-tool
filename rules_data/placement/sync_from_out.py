"""Copy Claude's built placement tables into the tracked rules_data/placement/ (round 33 step 1).

usage: python rules_data/placement/sync_from_out.py [pilot_structured_rules/placement/out]

Every file is copied as is, except placement_county.csv: a row whose county is not one of Texas's
254 counties is left out. HawkSoft's county field sometimes holds other text -- abbreviations,
policy-number digits, and fragments of street names and lender names ("...eimer Road",
"...k Home Mortg"). The app only ever looks up a county picked from the form's Texas list, so
those rows can never change a ranking, and they must not be committed. (Found 2026-10-09 in the
first build: 336 of 4,314 rows, 79 distinct values.) The cleaning belongs in Claude's builder;
this keeps the tracked copy clean whatever the builder does.
"""
import csv
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import intake_fields  # noqa: E402

FILES = ("placement_zip.csv", "placement_county.csv", "placement_profile.csv", "placement_markets.csv",
         "placement_meta.csv")
TEXAS = {c.title() for c in intake_fields.TEXAS_COUNTIES}


def main(src):
    for f in FILES:
        if f != "placement_county.csv":
            shutil.copyfile(os.path.join(src, f), os.path.join(HERE, f))
            continue
        with open(os.path.join(src, f), encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        keep = [r for r in rows if r["county"].strip().title() in TEXAS]
        with open(os.path.join(HERE, f), "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["month", "county", "market", "n"], lineterminator="\n")
            w.writeheader()
            w.writerows(keep)
        print(f"{f}: kept {len(keep)} of {len(rows)} rows ({len(rows) - len(keep)} with a non-county value)")
    print("copied:", ", ".join(FILES))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "pilot_structured_rules", "placement", "out"))
