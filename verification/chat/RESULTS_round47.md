# Ask the Guides: cross-carrier answers (round 47, 2026-11-05)

Liam and Jonathan, live: "Which carriers will take an above ground pool with no fence" covered 16 programs and left
the rest out ("did not come up, which is not acceptance"). Now a question about carriers in general sweeps every
program in the scope, each labelled by CFIG's eligibility check (`cloudflare/src/chat_sweep.js`,
`rules_data/chat/outcomes.json`). Model: Claude Sonnet 5.5. All runs: the Worker's own code path (`run_live.py`).

## a. Completeness and b. agreement (21 cross-carrier questions, `sweep_questions.csv`)

`python verification/chat/check_sweep_answers.py <run.jsonl>`: ALL OK on 21 of 21 (the final labels).
- (a) every program the checker shows for the scope is in the answer with a line (28 HO3, 14 DP3, 40 for a vacant
  home: the checker routes it to the dwelling programs); 0 lines needed filling from the rule text.
- (b) every label equals a fresh run of the checker (the export's code run anew, not the committed file): 0 mismatches.
  Where a label differs from the checker's raw status it is always something the neutral profile already lacked and
  the question is not about: the SageSure programs' county, Chubb's Coverage A. A label is about the topic only.

## c. Liam's question

"28 HO3 (owner-occupied home) programs, for an above-ground pool with no fence." Eligible 1 (Mercury); Eligible if
confirmed 8 (Foremost, Auros, Occidental, SURE, SafePort, Trium: fence vs pool-wall height; TWICO: signed liability
exclusion; Travelers: locking ladder or cover); Refer 3 (Allied Trust, Progressive, the Hartford: "refers unfenced
pools to underwriting as an unusual hazard", HAR-058); Not eligible 8 (ARI x2, Centauri, NatGen Custom360, Swyfft
x4); Coverage limited 4 (Orion180, Markel, Vave, Wilshire); Guide silent 3 (Chubb, HOAIC, Liberty Mutual); Closed 1.
15,311 + 1,296 tokens, $0.051; the labelled list at once, the model's first line 1.1 s, all of it 8.1 s.

## d. The round 45 40-question set (graded by an independent agent, two runs)

| run | correct | partly | wrong | made up | wrong carrier | citation wrong | label wrong |
|---|---|---|---|---|---|---|---|
| r46 run 2 (before) | 34 | 6 | 0 | 1 | 0 | 0 | 3 sections |
| r47 b (first sweep labels) | 36 | 4 | 0 | 0 | 0 | 0 | all 7 sweeps |
| r47 c (labels fixed) | 39 | 1 | 0 | 0 | 0 | 0 | 2 answers, 5 programs |

The 5 labels the last grade still found wrong (TWICO, Mercury, ARI x2 on stoves; Vave on acreage) are fixed in the
committed outcomes and re-checked live (X19, X20 above). What the grading found in the first sweep labels, all fixed:
- partial checks: a sweep ticked only the value's topic, so a rule that also needs the year built (Allied Trust's and
  Progressive's galvanized / polybutylene declines) was skipped -> now a full check, as the agent's own check runs;
- a guide silent on the item but with other rules on the topic was "Eligible" -> "Guide silent";
- row reading for items with no form answer (trampolines, stoves, acreage): "except trampolines" rows, damaged-
  structure declines and off-topic "farm / ranch" rows counted; conditional declines ("only with netting", "as the
  only heat source", "unless professionally installed" in the cure column) read as declines -> Confirm.
Unknown carriers: "Does State Farm take homes with a pool?" was swept until a sweep needed a cross-carrier phrase or
a name-free question; the model's other text (a refusal, a not-on-file line) is now shown above the list.
By design: "Federal Pacific" is the form's "Federal Pacific or Zinsco" answer, so Progressive (FPE only) is Confirm.

## e. Speed, CPU, cost

- Worker CPU (`bench_chat.mjs --fetch`, an idle laptop): sweeps median 1.5 ms, p95 2.3 ms, max 4.4 ms; other questions
  1.1 / 1.8 / 2.6 ms, against the Free plan's 10 ms. The chat index is 6.4 MB (was 4.9) and loads in about 60 ms.
- A sweep: the labels show at once (the Worker sends the list first); the model's first line median 1.1 s, all of it
  7.0 s (p95 8.8 s). Other questions: first words 1.0 s, full answer 2.9 s (medians).
- Cost: a sweep $0.039 on average (13,900 input + 1,050 output tokens), up to $0.071 (a vacant home, 40 programs);
  other questions about $0.01. The $3 daily cap covers about 75 sweeps a day.
