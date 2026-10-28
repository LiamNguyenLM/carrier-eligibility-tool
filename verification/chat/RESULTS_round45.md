# Ask the Guides: live test results (round 45, 2026-10-28)

40 questions (`questions.csv`), Claude Haiku 5.5 through the Worker's own code path (`run_live.py`). Each run was
graded by an independent agent against the expected answers, the rules CSVs and the guide chunks; I spot-checked
Q03, Q12, Q15, Q19, Q21, Q39 and Q40 and agreed with every grade.

| run | prompt | correct | partly | wrong | made up | wrong carrier | citation wrong | cost |
|---|---|---|---|---|---|---|---|---|
| 2 | first version | 34 | 6 | 0 | 0 | 1 | 1 | $0.031 |
| 3 | sources grouped by program (SDK) | 39 | 1 | 0 | 0 | 0 | 0 | $0.031 |
| 4 | sources grouped by program (SDK) | 38 | 2 | 0 | 0 | 0 | 1 | $0.031 |
| 6 | final: + one line per rule, no ranges (direct fetch) | 36 | 4 | 0 | 0 | 0 | 1 | $0.031 |

Target (Liam): no made-up content, no wrong carrier, at least 34/40 correct. Held on runs 3, 4 and 6 (run 2 had one wrong carrier, fixed by grouping the sources).

Known gaps (partly, recurring):
- Q19 (wood stoves, across carriers): the Hartford's three stove rows (HAR-013 Protection Class 10, HAR-014 installation,
  HAR-015 cleaning) are merged in a long list, attaching the PC 10 condition to installation. Runs 2, 3, 4 and 6.
- Q18 (acreage): Orion180's driveway requirement is tied to the 5-10 acre rule (runs 2 and 6).
- Q12 (Hartford losses): sometimes leaves out the fire-loss decline and the liability referral (runs 2 and 6).

Run 6 speed (this laptop to the API): first words median 0.66 s, p95 1.4 s; full answer median 1.6 s, p95 5.5 s.
