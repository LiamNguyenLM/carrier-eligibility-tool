# Ask the Guides: live test results (round 46, 2026-10-29)

Same 40 questions (`questions.csv`) and the same method as round 45 (`RESULTS_round45.md`): the Worker's own code path
(`run_live.py`), graded by an independent agent against the expected answers, the rules CSVs and the guide chunks.
This round the model is Claude Sonnet 5.5 (Liam), and the answer is one card per carrier program.

| run | model | prompt | correct | partly | wrong | made up | wrong carrier | verdict label wrong | cost |
|---|---|---|---|---|---|---|---|---|---|
| r45 run 6 | Haiku 5.5 | round 45 final | 36 | 4 | 0 | 0 | 0 | (no labels) | $0.031 |
| r46 run 1 | Sonnet 5.5 | cards (step 2) | 34 | 6 | 0 | 0 | 0 | 5 sections in 3 answers | $0.74 |
| r46 run 2 | Sonnet 5.5 | + verdict follows the table's effect, one program per section (step 4) | 34 | 6 | 0 | 1 | 0 | 3 sections in 2 answers | $0.75 |

Target (Liam, round 45): no made-up content, no wrong carrier, at least 34/40 correct. Run 1 met it; run 2 has one
made-up item: Q20's opening calls a Swyfft Benchmark Surplus row "an unclear scope" and counts "five more" coverage-only
programs (there are three). I checked Q20 against the sources and agree with the grader.

Sonnet is not better than Haiku on this set: the same or fewer correct, about 24x the cost, and slower.

Run 2 speed (this laptop to the API): first words median 1.2 s, p95 2.2 s; full answer median 3.3 s, p95 14.5 s (the
long cross-carrier answers). Cost: mean $0.019 a question, max $0.058. Worker CPU on these answers
(`bench_chat.mjs --fetch`, run 1): median 1.0 ms, p95 2.6 ms, max 4.2 ms.

Fixed this round, found by the grader:
- Source cards: a two-chunk guide source showed the second chunk's text under the first chunk's heading (11 cards in
  run 1, 0 in run 2). A card now shows the text the answer quoted from it, preferring the quote cited to that card.
- Quote check: 3 of run 1's 4 "quote not found" flags were the guide's sentence with the PDF's interleaved table column
  left out; now accepted. The 4th (Q11, a dropped "be") is a real misquote and is still flagged. Run 2: 0 flags.
- Verdict labels: Allied Trust's decline labelled Referral, Centauri's information row labelled Referral, and NatGen's
  Stab-Lok declines labelled Not addressed (run 1) are right in run 2; a group section (Q15) and a stray section on a
  not-on-file answer (Q26) are gone.

Still open:
- Never retrieved, so no model can cite them (tests marked todo in `cloudflare/test/chat.test.mjs`): Q14 TRV-013 (mold
  claim without MDR-1), Q18 ALL-167 (Allied Trust 5-10 acres referred before binding), Q19 HAR-075 (the Hartford rental
  program's stove decline). Both runs.
- Q16: a "Programs that decline galvanized plumbing" group section came back in run 2; Markel's coverage-only rows
  labelled Conditions in both runs.
- Q18: Orion180's driveway rule tied to the 5-10 acre band (round 45's gap, back in run 2); SageSure Occidental's
  referral labelled Conditions.
- Q25 / Q35: a stray closing line (a list "above" that isn't there; a "correction" to a correct earlier answer).
- Guide chunks whose stored section name is a page banner ("PRIVILEGED AND CONFIDENTIAL") or the wrong heading
  (Q15 S15, Q21 S14): the export, not the card.
