"""
COASTAL A/B: did the round 12 work actually stop ARI (HOA+) inheriting ARI
(HOB)'s "Homes 0-20 years old" age cap?

Reports VERDICT CORRECTNESS and TEXT CONTAMINATION as two separate numbers,
because they are two different failure modes with different consequences:

  * VERDICT correctness -- is ARI (HOA+) INELIGIBLE *because of* the
    borrowed age cap? That is what would actually stop an agent quoting a
    carrier that should have been quoted.
  * TEXT contamination -- does HOB's clause appear in HOA+'s output, and in
    what SHAPE? Three shapes, only one of which the citation-attribution
    validator can even see:

      MISLABELED_AS_OWN     the cap is presented as HOA+'s OWN rule ("the
                            HOA+ program's maximum age", "the carrier's
                            requirement"). The validator keys on a foreign
                            carrier LABEL, so this variant is invisible to
                            it by construction.
      LABELED_HOB_APPLIED   the cap is correctly attributed to HOB and then
                            applied to HOA+ anyway.
      CORRECT_DISMISSAL     the cap is named as HOB's specifically to explain
                            that HOA+ accepts homes over 20. Desired output,
                            not a defect.

IMPORTANT -- why the matcher is deliberately broad. The first version of
this script keyed on the literal string "0-20" and scored post-fix run 17
CLEAN. That run says "Home Age is 22 years, which exceeds the HOA+ program's
maximum age of 20 years for new business eligibility" -- textbook
MISLABELED_AS_OWN contamination, just paraphrased. Keying an analysis on the
one phrasing that happened to appear in the bug report is the same mistake
CLAUDE.md exists to prevent, so the cap is matched by MEANING (any 20-year
home-age limit) and attribution is decided separately.

TWO INDEPENDENT TEXT AXES -- do not add them together. The four shape
categories classify the REASONING and always sum to the run count. Citation
misattribution is a separate axis over the CITATIONS field, and the two
cross-cut: pre-fix, all 8 misattributed citations occurred in runs whose
reasoning was a CORRECT_DISMISSAL, i.e. the model argued correctly

    "exceeds the 20-year maximum for the HOB program but falls within
     HOA+ eligibility"

while stamping its supporting quote

    "ARI (HOA+): 'Homes 0-20 years old are eligible for this program.'"

Correct prose, misattributed evidence. The 5 MISLABELED_AS_OWN runs are the
mirror image: they carry no cap-bearing citation at all and assert the cap
in prose only. An earlier version of this report printed the citation number
indented under the shape counts, which read as a breakdown of them; it is
not, and the cross-tab is now printed so the relationship is explicit.

Every matched sentence is printed, so the classification can be checked by
eye rather than taken on trust -- the round 12 numbers were produced by hand
and these need to be comparable to them.

Usage:
    python verification/analyze_coastal_ab.py <postfix.json> <prefix.json>
"""
import json
import os
import re
import sys

# Any way of stating a 20-year home-age limit, not just the literal "0-20".
AGE_CAP_RE = re.compile(
    r"(0\s*-\s*20|20[\s-]*year|age of 20|over 20|older than 20|20 years old|exceeds? 20)",
    re.I,
)
# ...but only when the sentence is actually about the home's age / program
# eligibility, so an unrelated "20 years" (a roof band, say) is not counted.
AGE_CONTEXT_RE = re.compile(r"(home age|home[s]? \d|age is|years old|age limit|maximum age|program)", re.I)

# The cap is attributed to the OTHER program (correct attribution).
HOB_ATTRIBUTION_RE = re.compile(r"\bho[\s\-_]?b\b", re.I)
# The cap is attributed to the carrier being evaluated (contamination).
SELF_ATTRIBUTION_RE = re.compile(
    r"(this program|this carrier|the carrier'?s? (own )?(requirement|rule|guideline|maximum)"
    r"|hoa\s*\+|hoa plus program'?s|program'?s maximum age|for new business eligibility)",
    re.I,
)
# HOA+ is stated to ACCEPT homes over 20 -- the exculpatory half.
EXCULPATORY_RE = re.compile(
    r"(accepts? homes over 20|considered for coverage under|does not apply|doesn'?t apply"
    r"|not applicable|hoa[/ ]hoa plus (program )?(accepts?|can|considers?)|over 20 years old can be"
    r"|is the appropriate program|no maximum age|does not impose)",
    re.I,
)
ADVERSE_RE = re.compile(
    r"(exceeds|not eligible|ineligible|does not (meet|qualify)|fails|outside|beyond)", re.I
)


def _text_fields(result):
    return (
        result.get("reasons", [])
        + result.get("citations", [])
        + result.get("missing_info", [])
        + [result.get("notes", "")]
    )


def _find_hoa_plus(run):
    for r in run.get("carriers", []):
        name = r.get("carrier", "").upper().replace(" ", "").replace("_", "")
        if "ARI" in name and ("HOA+" in name or "HOAPLUS" in name):
            return r
    return None


def _cap_sentences(result):
    out = []
    for field in _text_fields(result):
        for piece in re.split(r"(?<=[.;])\s+", field):
            if AGE_CAP_RE.search(piece) and AGE_CONTEXT_RE.search(piece):
                out.append(piece.strip())
    return out


# Worst-first: a run is classified by its worst sentence.
_SEVERITY = {"MISLABELED_AS_OWN": 3, "LABELED_HOB_APPLIED": 2, "CORRECT_DISMISSAL": 1, "NONE": 0}


def _classify_sentence(sentence):
    """Classify ONE sentence.

    Per-sentence, deliberately. Pooling every cap sentence together and
    asking "does HOB appear anywhere?" scored pre-fix runs 1, 12 and 15 as
    CORRECT_DISMISSAL: each of them has a properly labeled
    "ARI (HOB): 'Homes 0-20 years old...'" citation, which masked the
    sentence that actually matters --

        "Home age is 22 years, which exceeds THE CARRIER'S REQUIREMENT that
         homes be 0-20 years old FOR THIS PROGRAM."

    That is the borrowed cap applied to HOA+ as its own rule. (The following
    sentence then refers the risk to "HOA/HOA Plus instead" -- which IS
    HOA+, the very carrier being evaluated, so the run also contradicts
    itself.) A clean citation elsewhere in the same result does not undo it.
    """
    adverse = bool(ADVERSE_RE.search(sentence))
    exculpatory = bool(EXCULPATORY_RE.search(sentence))
    says_hob = bool(HOB_ATTRIBUTION_RE.search(sentence))
    says_self = bool(SELF_ATTRIBUTION_RE.search(sentence))

    # Self-attribution wins over HOB-attribution when both appear: naming
    # HOB and then calling the cap "this program's" is still contamination.
    if says_self and adverse and not (says_hob and exculpatory):
        return "MISLABELED_AS_OWN"
    if says_hob:
        if adverse and not exculpatory:
            return "LABELED_HOB_APPLIED"
        return "CORRECT_DISMISSAL"
    if adverse and not exculpatory:
        # applied against this carrier with no attribution at all
        return "MISLABELED_AS_OWN"
    return "CORRECT_DISMISSAL"


def misattributed_citations(result):
    """Citations that carry HOB's age cap but are NOT labeled as HOB.

    Tracked as its own number because it is a distinct defect from the
    reasoning shape, and because it is precisely the variant
    _strip_misattributed_citations() is blind to: that validator removes a
    citation whose LABEL names a different carrier, so a citation labeled
    "ARI (HOA+):" that quotes HOB's text sails straight through.

    This is also where a per-run hand count and a reasoning-level count
    diverge. Pre-fix runs 0, 2, 4 and 6 all reason correctly ("exceeds the
    20-year maximum for the HOB program but falls within HOA+ eligibility")
    while still carrying a citation stamped
    "ARI (HOA+): 'Homes 0-20 years old are eligible for this program.'"
    Correct prose, misattributed evidence -- so they count here and not as
    a reasoning contamination.
    """
    out = []
    for c in result.get("citations", []):
        if not (AGE_CAP_RE.search(c) and AGE_CONTEXT_RE.search(c)):
            continue
        label = c.split(":", 1)[0] if ":" in c else ""
        if HOB_ATTRIBUTION_RE.search(label):
            continue  # correctly attributed to HOB
        out.append(c)
    return out


def classify(result):
    """Returns (cap_drove_verdict, shape, evidence)."""
    status = result.get("status", "?")
    sentences = _cap_sentences(result)
    if not sentences:
        return False, "NONE", []

    per_sentence = [(s, _classify_sentence(s)) for s in sentences]
    shape = max((sh for _, sh in per_sentence), key=lambda s: _SEVERITY[s])

    contaminated = shape in ("MISLABELED_AS_OWN", "LABELED_HOB_APPLIED")
    cap_drove_verdict = status in ("INELIGIBLE", "REFER") and contaminated
    # Surface the sentences that drove the classification first.
    ordered = sorted(per_sentence, key=lambda p: -_SEVERITY[p[1]])
    return cap_drove_verdict, shape, [f"[{sh}] {s}" for s, sh in ordered]


def analyze(label, path):
    with open(path) as f:
        data = json.load(f)
    runs = [r for r in data.get("runs", []) if "carriers" in r]
    errors = data.get("errors", [])

    print("=" * 78)
    print(f"{label}   ({len(runs)} completed run(s), {len(errors)} error record(s))")
    print("=" * 78)

    cap_ineligible = 0
    cap_adverse = 0
    mis_cited = 0
    crosstab = {}
    other_ineligible = 0
    shapes = {}
    missing = 0
    for i, run in enumerate(runs):
        r = _find_hoa_plus(run)
        if r is None:
            missing += 1
            print(f"  run {i:2d}: ARI (HOA+) ABSENT")
            continue
        drove, shape, evidence = classify(r)
        bad_cites = misattributed_citations(r)
        if bad_cites:
            mis_cited += 1
        status = r.get("status", "?")
        if drove:
            cap_adverse += 1
            if status == "INELIGIBLE":
                cap_ineligible += 1
        elif status == "INELIGIBLE":
            other_ineligible += 1
        shapes[shape] = shapes.get(shape, 0) + 1
        key = (shape, bool(bad_cites))
        crosstab[key] = crosstab.get(key, 0) + 1
        mark = "  <== CAP DROVE AN ADVERSE VERDICT" if drove else ""
        cite_mark = "  [misattributed citation]" if bad_cites else ""
        print(f"  run {i:2d}: {status:26s} {shape}{mark}{cite_mark}")
        for line in evidence[:2]:
            print(f"           | {line[:145]}")

    n = len(runs) - missing
    contaminated = shapes.get("MISLABELED_AS_OWN", 0) + shapes.get("LABELED_HOB_APPLIED", 0)
    print()
    print(f"  --- {label}: {n} evaluable run(s) ---")
    if n:
        print(f"  VERDICT  INELIGIBLE caused by the borrowed cap : {cap_ineligible}/{n} = {cap_ineligible/n:.0%}")
        print(f"           any ADVERSE verdict (incl. REFER)     : {cap_adverse}/{n} = {cap_adverse/n:.0%}")
        print(f"           INELIGIBLE on other grounds           : {other_ineligible}/{n}")
        print()
        print(f"  TEXT AXIS 1 -- REASONING shape (these sum to {n})")
        print(f"      MISLABELED_AS_OWN    {shapes.get('MISLABELED_AS_OWN', 0):2d}  (validator is blind to this)")
        print(f"      LABELED_HOB_APPLIED  {shapes.get('LABELED_HOB_APPLIED', 0):2d}")
        print(f"      CORRECT_DISMISSAL    {shapes.get('CORRECT_DISMISSAL', 0):2d}  clean")
        print(f"      NONE                 {shapes.get('NONE', 0):2d}  clean")
        print(f"      -> reasoning contaminated: {contaminated}/{n} = {contaminated/n:.0%}")
        print()
        print(f"  TEXT AXIS 2 -- CITATION misattributed (independent of axis 1; do NOT add)")
        print(f"      -> {mis_cited}/{n} = {mis_cited/n:.0%} of runs carry the cap in a citation not labeled HOB")
        print()
        print(f"  CROSS-TAB (reasoning shape x misattributed citation)")
        for (shape_key, bad) in sorted(crosstab):
            print(f"      {shape_key:20s} bad_citation={'YES' if bad else 'no ':3s} -> {crosstab[(shape_key, bad)]:2d}")
    print()
    return {"label": label, "n": n, "cap_ineligible": cap_ineligible,
            "cap_adverse": cap_adverse,
            "other_ineligible": other_ineligible, "shapes": shapes,
            "contaminated": contaminated, "mis_cited": mis_cited, "errors": len(errors)}


def main():
    post = analyze("POST-FIX (main @15b141d)", sys.argv[1])
    pre = analyze("PRE-FIX  (worktree @c7eab14)", sys.argv[2])

    print("=" * 78)
    print("SIDE BY SIDE")
    print("=" * 78)
    def row(name, a, b):
        print(f"{name:38s}{a:>19s}{b:>19s}")
    row("", "PRE-FIX", "POST-FIX")
    row("completed runs", str(pre["n"]), str(post["n"]))
    def pct(d, key):
        return f"{d[key]}/{d['n']} = {d[key]/d['n']:.0%}" if d["n"] else "n/a"
    row("VERDICT: cap caused INELIGIBLE", pct(pre, "cap_ineligible"), pct(post, "cap_ineligible"))
    row("         cap caused ANY adverse verdict", pct(pre, "cap_adverse"), pct(post, "cap_adverse"))
    row("         INELIGIBLE, other grounds", str(pre["other_ineligible"]), str(post["other_ineligible"]))
    row("TEXT axis 1: reasoning contaminated", pct(pre, "contaminated"), pct(post, "contaminated"))
    row("TEXT axis 2: citation misattributed", pct(pre, "mis_cited"), pct(post, "mis_cited"))
    print("             (the two TEXT axes are independent -- see the cross-tab above; adding them is wrong)")
    for shape in ("MISLABELED_AS_OWN", "LABELED_HOB_APPLIED", "CORRECT_DISMISSAL", "NONE"):
        row("   axis 1: " + shape, str(pre["shapes"].get(shape, 0)), str(post["shapes"].get(shape, 0)))


if __name__ == "__main__":
    main()
