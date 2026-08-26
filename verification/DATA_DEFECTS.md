# Data defects — wrong PDF ingested, needs a human, not a code change

These are not bugs in the pipeline. The pipeline reads whatever document it
is given and reasons about it correctly, which is exactly what makes these
dangerous: a mis-filed PDF produces confident, well-cited answers about the
*wrong program* rather than an error anyone would notice.

Both were found in round 16, and neither was found by looking for it — one
surfaced because a manual audit asked an unrelated question about a
condo-claim citation, and the other only because that first one prompted a
sweep of the whole corpus for duplicate content.

`test_no_two_carriers_hold_the_same_document` now checks this on every run.
It is an `xfail` listing both pairs; it will XPASS once the PDFs are fixed,
which is the signal that this file can be deleted.

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

## Why this class is worth a standing test

Neither defect is visible in the tool's output. Both records return
plausible, cited, internally-consistent analysis. The only way to see the
problem is to compare a record's content against what its *name* claims it
is — which is what the duplicate check now does automatically, and what a
future ingest of two genuinely different programs would still pass.

A caveat on the check's limits: it catches a record holding a *duplicate* of
another record's file. It would **not** catch a record holding some third,
entirely wrong PDF that appears nowhere else in the corpus. If a stronger
guarantee is ever wanted, the natural check is that each document's own text
contains a product token consistent with its filename — `carrier_programs()`
already computes the filename half of that comparison.
