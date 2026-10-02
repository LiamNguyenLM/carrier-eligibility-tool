# Data defects — wrong PDF ingested, needs a human, not a code change

These are not bugs in the pipeline. The pipeline reads whatever document it
is given and reasons about it correctly, which is exactly what makes these
dangerous: a mis-filed PDF produces confident, well-cited answers about the
*wrong program* rather than an error anyone would notice.

DD-1 and DD-2 were found in round 16, and neither was found by looking for
it — one surfaced because a manual audit asked an unrelated question about a
condo-claim citation, and the other only because that first one prompted a
sweep of the whole corpus for duplicate content. DD-3 was found in round 17
while building the chat tab, and is a different shape again: a record holding
no document rather than the wrong one. DD-4 was found in round 17 too.

`data_defects.defective_programs()` is the RUNTIME list, and it derives all
four rather than naming them, so each clears itself once the PDF is fixed.
Since 2026-09-29 the eligibility check leaves every program on it out of the
prompt and shows it under **Could Not Be Checked** with a fixed row: "The
guide on file is the wrong document" (or "has no readable text"), "check
with the carrier directly". Centauri HO3 is known to production only through
`expected_programs.txt`, because Railway has no PDF folder. That list says
only which programs should exist; presence and defects always come from the
database. The re-upload procedure is in handoff.md, "Updating carrier guides
in production".
Two standing tests also cover part of this class on every run --
`test_no_two_carriers_hold_the_same_document` and
`test_each_document_reads_like_the_product_its_filename_claims`. Both are
`xfail` naming the defects below; both XPASS once the PDFs are fixed, which
is the signal to **remove their xfail markers** (so a future mis-ingest fails
the build) and delete this file. See "What the two checks do and do not
cover" at the bottom -- they are complementary, and each known defect is
caught by only one of them.
---

## DD-1 — `NatGen_Custom360_HO3` holds the DP3 (Landlord) document

**Severity: highest of the two.** This one affects owner-occupied queries,
which is the primary use case.

```
NatGen_Custom360_DP3_-_06.25.2026   112 chunks   sha256[:12]=3db6de399c91
NatGen_Custom360_HO3_-_06.25.2026   112 chunks   sha256[:12]=3db6de399c91   <- identical
```

The shared document is titled **"Texas Landlord — Custom360 TEXAS Landlord"**
(Imperial Fire and Casualty, form 15606), with 31 occurrences of "landlord",
one of "dwelling fire", and **zero** occurrences of "HO3", "HO-3" or
"homeowners". So the DP3 record is the correct one and the **HO3 record is
wrong** — NatGen Custom360's homeowners guide was never ingested.

Measured over the round 15 STANDARD (owner-occupied) sweep, n=20:

| | |
|---|---|
| appears in output | 20/20 runs |
| status | INELIGIBLE 18/20, INSUFFICIENT_INFORMATION 2/20 |
| output identifies it as a landlord program | 20/20 |

The model is behaving correctly — it reads the document, sees a landlord
program, and says it does not apply to an owner-occupied risk. But the
*consequence* is that every owner-occupied query tells an agent this carrier
is not applicable, when the truth is that we have no data for its homeowners
program at all. A carrier that might well be eligible is being reported as
ineligible.

**Fix:** upload the real NatGen Custom360 **HO3** guide over the HO3 record.

---

## DD-2 — `Liberty_Mutual_HO6` holds the HO3 document

Backlogged since rounds 9-11 as "HO6 source file is identical to HO3"; round
16 confirmed it and established that no code change can address it.

```
Liberty_Mutual_HO3_-_02.21.2026   27 chunks   sha256[:12]=4949962c3eb9
Liberty_Mutual_HO6_-_02.21.2026   27 chunks   sha256[:12]=4949962c3eb9   <- identical
```

The only occurrence of "condominium" in either document is a single row of a
Minimum Coverage Requirements table:

```
| Coverage C | Condominium | $20,000 |
```

That is a coverage limit, not a condominium-program eligibility rule. So the
Condominium Unit-Owners guide was never ingested.

`test_liberty_mutual_ho6_condo_claim_is_grounded_in_real_text` measured
**5/20 = 25%** over the round 15 sweep — and the passes are the model
inferring the product from the FILENAME, not from retrieved rule text. Its
own citation gives the game away:

> "Liberty_Mutual_HO6: The document title and content indicate this is a
> 'Condominium Unit-Owners Program'."

Less severe than DD-1 because HO6/condo is a smaller slice of this agency's
book, but the same shape: confident answers about a program we have no
document for.

**Fix:** upload the real Liberty Mutual **HO6** (Condominium Unit-Owners)
guide over the HO6 record.

---

## DD-3 — `Centauri_-_HO3_-_05.01.2026` produced no text at all

**Found round 17**, while building the chat tab. Not found by either standing
check, and neither could have found it.

```
Centauri_-_HO3_-_05.01.2026    0 chunks    (3.5 MB PDF on disk)
Centauri_-_DP3_-_11.16.2022   38 chunks
```

The PDF is a scan with no text layer, so extraction yielded nothing and the
loader wrote zero chunks. The program is therefore **absent from the vector
store entirely** — 40 carriers are indexed and this is not one of them.

This is a third shape, distinct from DD-1 and DD-2. Both of those are records
holding the WRONG document; this is a record holding NO document. It is the
most invisible of the three:

- The eligibility pipeline never considers the program, so it never appears in
  any output to be noticed as wrong.
- `test_no_two_carriers_hold_the_same_document` and
  `test_each_document_reads_like_the_product_its_filename_claims` both iterate
  over records that EXIST in the store. A record that produced no chunks is
  not there to be checked by either one.

It was reachable from the chat tab, though, and dangerously: building the
carrier-name index from stored programs alone made "Centauri HO3 roof age"
resolve to **Centauri's DP3 (dwelling fire) guide**, because the HO3 record was
not a candidate and the product filter had nothing to narrow to. An agent
asking a homeowners question would have been handed a dwelling-fire rule with
nothing flagged.

Note the difference from DD-1, because it is easy to overstate the parallel:
NatGen's mis-filed document really is *titled* "Texas Landlord" and says
"landlord" 31 times. Centauri's DP3 document says "landlord" **zero** times.
Its only occupancy mention is a single "The home is tenant occupied" — and
that appears in a list of circumstances requiring underwriting approval prior
to binding, not as the document's own product identity. So the defect here is
purely wrong-PRODUCT (dwelling fire answered for a homeowners question); there
is no landlord-branding tell of the kind that made DD-1 visible on sight.

On the chat-tab branch, `chat.known_programs()` unions the defect list in so
the program is nameable and can be refused by name.

**Fix:** OCR the Centauri HO3 PDF and re-ingest it, or obtain a text-layer
copy from the carrier.

**Detection now lives in `data_defects.py`**, which derives all three defects
rather than listing them, so each clears on its own once the PDF is fixed.
`NO_TEXT` is detected by comparing the PDFs on disk against the programs in
the store — the filesystem is the only place a zero-chunk document leaves a
trace.

---

## DD-4 — `Sage_-_Occidental_HO3` holds Occidental's DP3 (Dwelling Fire) guide

**Found round 17**, while checking the Sage family's trust/LLC rules against
their own headings. (DD-3, Centauri HO3's zero-chunk scan, is recorded on the
`chat-tab` branch and lands here when that branch merges.)

The record named HO3 is the **08/06/2025 revision of Occidental's DWELLING
FIRE PROGRAM (DP3) guide**. The DP3 record holds the 10/24/2025 revision of
the same guide:

```
                         header                                   revised     policy form
Sage_-_Occidental_HO3    TEXAS OCCIDENTAL DWELLING FIRE PROGRAM (DP3)  08/06/2025  DP 00 03
Sage_-_Occidental_DP3    TEXAS OCCIDENTAL DWELLING FIRE PROGRAM (DP3)  10/24/2025  DP 00 03
```

84% text overlap between the two, identical form numbers, and **zero**
references to any HO product or HO policy form in the "HO3" record. Its own
Forms row reads "These forms are eligible: • Dwellings: DP 00 03", and its
eligibility list reads "Dwellings (DP 00 03) must be: One to four family. o
Owner or Tenant occupied." Occidental's homeowners guide was never ingested.

**Why neither standing check caught it, and why that matters most:**

- **Duplicate hash**: the two records are different *revisions*, so their
  bytes differ. A hash check can only ever catch an exact copy.
- **Product check (as tuned in round 16)**: it counted "owner occupied" as a
  homeowners self-description, and dwelling-fire guides say it constantly --
  5 of this record's 6 "homeowners" hits were "owner occupied", so a DP3
  guide scored 6 HO vs 5 DP and read as homeowners. Worse, a header-based
  version of the check had **caught this exact record** ("Sage Occidental HO3
  (1 vs 2)") and was recorded as a false positive and tuned away. The trip
  was correct.

**Fixed in the check, not the data:** a second, reference-based rule now
counts only the policy forms and product names a guide gives itself (HO 00
0x / HO-3 / "homeowners program" vs DP 00 0x / DP3 / "dwelling fire
program"), with endorsement numbers excluded. Over every single-product
record, Occidental HO3 is the only one with 0 own-product references and any
opposite ones (0 vs 5). `TestProductCheckCalibration` pins the result both
ways every commit: Travelers (0 vs 0 — it cannot trip a reference rule),
Vave HO3 (19 vs 4), Markel HO3 (32 vs 1), Liberty Mutual DP3 (0 vs 1, a
cross-reference to Safeco's homeowners program) and the correct Occidental DP3
record all stay unflagged. "owner occupied" was **kept** in the word rule:
removing it was measured and moves Travelers from 3 vs 8 (ratio 2.7) to 1 vs 8
(ratio 8), protected only by the 10-hit floor.

**What was built on the wrong document**, and what was done about each:

| where | claim | round 17 |
|---|---|---|
| `structured_rules.sage_family_fpc_eligibility` | Occidental's row 5 lacks "no rental exposures allowed" (3-condition carve-out) | **Annotated**: confirmed for DP3 only, unverified for HO3. Not reverted to the 4-condition version -- that is equally a guess. |
| `test_occidental_variant_lacks_no_rental_condition_others_have` | same, as a source-text claim | **Retargeted** to the DP3 record, with the premise asserted against its text |
| `test_both_low_and_high_fpc_rows_retrievable`, the "classification" guard, the pool-spec row ("minimum height of 4 feet") | claims about the document's own text | **Retargeted** to `Sage_-_Occidental_DP3`, which holds the same text |
| `test_fpc_conclusion_in_reasons_still_upgrades_verdict` | override wiring; carrier incidental | **Moved** to Sage SURE HO-3 |
| `test_sage_family_ppc1_is_eligible_not_insufficient[Occidental]`, `test_sage_occidental_pool_fence_consistency`, `test_sage_family_ppc1_pass_rate`, `test_prose_only_cross_carrier_bleed_is_absent` | end-to-end HO3 verdicts in owner-occupied runs | **Annotated, still running**: cannot be retargeted (the DP3 record is not evaluated for owner-occupied profiles). The param id and printed rate now say "not HO3 evidence" on every run. Two of these passed in round 16's baseline -- against the DP3 text. |
| `eligibility_check.py` comments (the `_mentions_pool_rule` "#19/57" finding and others) | retrieval findings measured on this record | **Left as-is** -- still true of the text on file; recorded here instead of edited, to avoid a comment-only conflict with branches changing that file |

**Fix:** upload Occidental's real HO3 (homeowners) guide over the HO3 record,
then revisit every row above -- starting with the carve-out, which will need
re-confirming against the real text in one direction or the other.

---

## DD-5 — all four Swyfft guides lost their fi / fl ligatures (recorded 2026-10-02, round 24)

**Not a mis-filed PDF:** the right documents are on file, but some of their
words are broken. **Record only; Liam decides when to fix it.**

**What is stored.** Every "fi" and "fl" ligature in the four Swyfft PDFs is
stored as a NUL character (`\x00`). Only Swyfft is affected; no other
program's stored text contains a NUL.

| Program | NUL characters | Chunks |
|---|---|---|
| Swyfft_-_Benchmark_(Admitted)_HO3 | 9 | 15 |
| Swyfft_-_Benchmark_(Surplus)_HO3 | 10 | 15 |
| Swyfft_-_Lloyds_(Surplus)_HO3 | 8 | 19 |
| Swyfft_-_Topa_(Surplus)_HO3 | 11 | 16 |

By word, over all four guides (␀ marks the NUL):

| Stored as | Should read | Count |
|---|---|---|
| Paci␀c | Pacific | 5 |
| Roo␀ng | Roofing | 4 |
| ␀le | file | 4 |
| re␀ects | reflects | 4 |
| land␀lls | landfills | 4 |
| retro␀tted | retrofitted | 4 |
| ␀rst | first | 4 |
| ␀re | fire (e.g. "Prior liability or ␀re loss at any location") | 4 |
| certi␀ed | certified | 3 |
| Bene␀ts | Benefits | 2 |

**Why it matters.** Retrieval embeds the broken words, and every keyword
check misses them: "fire", "file", "first", "Roofing", "landfills",
"certified". The guides' "flat" and "flood" happen not to be ligated in
these PDFs, but nothing guarantees that.
- The round 23 pilot workbook's quote check fails on these rows for the
  same reason.
- In the same text, the bullet glyph is stored as U+FFFD.

**Cause** (confirmed 2026-10-02). It comes from pdfplumber itself:
`page.extract_text()` on `carrier_eligibility_pdfs/Swyfft_-_Benchmark_(Admitted)_HO3.pdf`
returns 9 NULs. The glyphs sit in subset Roboto fonts (`AKBJSY+Roboto-Bold`,
`BEGEVY+Roboto-Regular`) whose ToUnicode map has no entry for the
ligatures.

**The fix** (not done):
1. In the loader's text extraction (`pdf_extraction.py`), recover the
   ligature, either from the glyph name or by trying "fi" and "fl" against
   a word list. A NUL alone does not say which ligature it was.
2. Add a load-time check that fails on any NUL in extracted text, so it
   cannot recur silently.
3. **Re-seed** the four Swyfft programs: re-upload, or a full re-index (see
   handoff.md, "Updating carrier guides in production", and the
   FORCE_RESEED warning there).
4. Re-run the pilot workbook's Swyfft quote check afterwards.

## Why this class is worth a standing test

Neither defect is visible in the tool's output. Both records return
plausible, cited, internally-consistent analysis. The only way to see the
problem is to compare a record's content against what its *name* claims it
is — which is what the duplicate check now does automatically, and what a
future ingest of two genuinely different programs would still pass.

### What the two checks do and do not cover

Round 16 added a second, independent check after the first one's limits were
noted. Neither subsumes the other, and together they are still narrower than
"every carrier's document is correct" — a future reader should not assume
more coverage than this:

| | catches | misses |
|---|---|---|
| `test_no_two_carriers_hold_the_same_document` | a record holding a copy of **another tracked record's** file, whatever product it is | a wrong file that is **unique** in the corpus |
| `test_each_document_reads_like_the_product_its_filename_claims` | a record whose document is the **wrong product**, even if unique -- by word counts (DD-1) or, since round 17, by the policy forms and program name it gives itself (DD-4, a different *revision* of its sibling, so no hash could see it) | a wrong file of the **right product** |

Each of the two known defects is caught by exactly one of them, which is why
both exist:

- **DD-2 (Liberty Mutual HO6)** is caught only by the duplicate check. The
  document it holds is the HO3 guide — still a homeowners document, so its
  product signals agree with its filename and the product check is silent.
- **DD-1 (NatGen Custom360 HO3)** is caught by both, but the product check
  would catch it even if the DP3 record did not exist to duplicate.

**What NEITHER catches:** a record holding the wrong document of the *right*
product, where that file is also unique — one homeowners carrier's guide
filed under a different homeowners carrier's name, say. Detecting that needs
the carrier's own name to appear reliably in its text, which these documents
do not do. If that ever matters, it is a manual spot-check, not a test.

The product check is a heuristic with deliberate margins: it fires only when
a document's opposite-product mentions are both ≥10 and ≥4× its own-product
mentions. Travelers' HO3 guide legitimately contains a "LANDLORD DWELLING /
LANDLORD CONDOMINIUM ONLY" ineligibility section (3 vs 8, ratio 2.7) and must
not trip; NatGen Custom360's mis-filed record is 2 vs 34, ratio 17. A
header-only variant was tried and rejected — it tripped on Sage Occidental
HO3 and Travelers on one-hit margins.
