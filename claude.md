# Testing & Regression Policy — Carrier Eligibility Tool

This project has a history of fixes that either (a) only patch the exact
wording of the bug report instead of the underlying rule, or (b) get
silently reverted by a later change with nobody noticing until the next
manual audit. Both are expensive: the only thing currently catching either
one is a full re-read of real carrier PDFs by a human/agent, every round.
The rules below exist to make that unnecessary for anything that's already
been found once.

## Before you say a finding is "fixed"

1. Add or update a test in `test_eligibility_matrix.py` that encodes the
   *exact* scenario from the audit finding — not a simplified version of it.
2. If the fix targets a general rule (a terminology mapping, an
   AND-conditioned eligibility clause, a bucket/verdict label, anything that
   isn't specific to one carrier's exact wording), add at least **two** test
   cases using different phrasings of the same underlying concept. Round 11
   found that the Allied Trust "Composition Shingle" fix only worked for the
   literal wording already in the bug — a test suite with only that one
   phrasing would have shipped a fix that doesn't generalize as "done."
3. Run the full suite and paste the actual pass/fail output into your
   summary. "Verified" or "should work now" is not a substitute for a green
   test. If you can't run the suite for some reason, say so explicitly
   instead of asserting a result you didn't check.

## When you decide NOT to fix something this round

Add the test anyway, marked `xfail` with a one-line reason. A backlog item
that only exists in a PDF someone read three rounds ago gets forgotten. A
backlog item that shows up as a named `xfail` every time the suite runs
stays visible until someone deliberately removes it.

## Priority order when a batch of findings comes in from an audit

1. Anything that changes a carrier's final verdict (Eligible / Ineligible /
   Insufficient Information / One Issue) — these are the ones that would
   actually mislead an agent.
2. Anything that has now reproduced identically across more than one
   customer profile. These are usually small, isolated, and cheap to fix —
   check test history for repeat offenders before starting on anything else.
3. Everything else.

Do not default to fixing findings in the order they're listed in the audit
narrative. The order they were written up in is not a priority ranking.

## Two tiers of tests

- **Retrieval tests** (fast, no LLM call). For every "guaranteed lookup"
  topic (PPC, pool, solar, roof age, ...), assert the retrieval step
  actually returns the carrier's real rule text for that topic. These
  should run on every commit — they're what would have caught "Progressive
  HO3's solar exclusion is verified fixed" not actually firing on the very
  next run.
- **Baseline profile tests** (slower — they call the full pipeline).
  2-3 fixed customer profiles with known-correct expected verdicts, taken
  from completed audits. Run these before merging anything that touches
  prompts, retrieval, ranking, or bucket logic — not only when someone
  happens to schedule another full audit.

## Flakiness is a bug, not a caveat

If you describe a fix as working "in most runs," "usually," or "verified"
without having run it more than once, that's not a passing state — it's an
undisclosed failure rate. Either make the affected step deterministic
(e.g. temperature 0 for that call), or run the relevant baseline test 3-5
times in a row and report the actual pass rate. "Occasionally gets
distracted, not fully solved" belongs in a test assertion, not only in a
prose summary.