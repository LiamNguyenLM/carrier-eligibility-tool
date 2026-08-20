"""
Turns the saved sweep_*_results.json files into the real pass-rate table.

Every metric is computed from the SAME saved runs, so a single batch of API
calls measures every hard-assert, xfail, and xpass for that profile at once.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HERE = os.path.dirname(__file__)


def load(name):
    path = os.path.join(HERE, f"sweep_{name}_results.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [r for r in json.load(f)["runs"] if "carriers" in r]


def find(run, *needles, exclude=()):
    for r in run["carriers"]:
        c = r.get("carrier", "").lower()
        if all(n.lower() in c for n in needles) and not any(x.lower() in c for x in exclude):
            return r
    return None


def blob(r, *fields):
    if r is None:
        return ""
    parts = []
    for f in fields:
        v = r.get(f, [])
        parts.extend(v if isinstance(v, list) else [v])
    return " ".join(parts).lower()


ALL_TEXT = ("reasons", "citations", "missing_info", "notes")


def rate(outcomes):
    valid = [o for o in outcomes if o is not None]
    if not valid:
        return None, 0
    return sum(valid) / len(valid), len(valid)


def report(title, rows):
    print(f"\n{'='*78}\n{title}\n{'='*78}")
    print(f"{'metric':<58}{'rate':>9}{'n':>6}")
    print("-" * 78)
    for label, outcomes in rows:
        r, n = rate(outcomes)
        if r is None:
            print(f"{label:<58}{'NO DATA':>9}{0:>6}")
            continue
        flag = "" if r == 1.0 else ("   <-- FLAKY" if r > 0 else "   <-- ALWAYS FAILS")
        print(f"{label:<58}{r:>8.0%}{n:>6}{flag}")


def main():
    std = load("standard")
    alt = load("alt")

    # ---------------- STANDARD PROFILE ----------------
    if std:
        ari_verdict, ari_prose, ari_cite = [], [], []
        for run in std:
            r = find(run, "hoa+")
            if r is None:
                ari_verdict.append(None); ari_prose.append(None); ari_cite.append(None); continue
            # 1. VERDICT correctness: not wrongly declined on the age cap
            text = blob(r, *ALL_TEXT)
            has_agecap = "0-20 years" in text or "hoa plus" in text or "hoa/hoa" in text
            ari_verdict.append(not (r.get("status") == "INELIGIBLE" and has_agecap))
            # 2. PROSE cleanliness: HOB's rule text absent everywhere
            ari_prose.append(not has_agecap)
            # 3. CITATIONS specifically (what the validator actually strips)
            ari_cite.append(not any(
                "0-20 years" in c.lower() or "hoa plus" in c.lower()
                for c in r.get("citations", [])
            ))

        report("STANDARD PROFILE (PPC 9, 2009, 10yr comp shingle, fenced pool)", [
            ("P1 ARI HOA+: verdict not wrongly INELIGIBLE via age cap", ari_verdict),
            ("P1 ARI HOA+: HOB age-cap text absent from CITATIONS", ari_cite),
            ("P1 ARI HOA+: HOB age-cap text absent from ALL prose", ari_prose),
            ("P3 Swyfft Lloyds == INELIGIBLE (was 80%)", [
                (lambda r: r and r.get("status") == "INELIGIBLE")(find(run, "lloyds")) for run in std]),
            ("P3 Orion == ELIGIBLE (was 40%)", [
                (lambda r: r and r.get("status") == "ELIGIBLE")(find(run, "orion")) for run in std]),
            ("P3 Mercury == ELIGIBLE (hard assert, unmeasured)", [
                (lambda r: r and r.get("status") == "ELIGIBLE")(find(run, "mercury")) for run in std]),
            ("P3 Sage Occidental pool fence surfaced (was 55%)", [
                ("fenc" in blob(find(run, "occidental"), *ALL_TEXT)
                 or "gate" in blob(find(run, "occidental"), *ALL_TEXT)) for run in std]),
            ("xfail Foremost county restriction flagged", [
                "county" in blob(find(run, "foremost"), "missing_info") for run in std]),
            ("xfail CHUBB cites 'a house' clause", [
                "house" in blob(find(run, "chubb"), "citations") for run in std]),
            ("xfail Liberty Mutual HO6 condo claim grounded", [
                "condominium" in blob(find(run, "liberty mutual ho6"), "citations") for run in std]),
        ])

    # ---------------- ALT PROFILE ----------------
    if alt:
        report("ALT PROFILE (PPC 1, 1994, 14yr comp shingle, solar panels)", [
            ("P2 xpass Sage Auros != INSUFFICIENT_INFO", [
                (lambda r: r and r.get("status") != "INSUFFICIENT_INFORMATION")(find(run, "auros")) for run in alt]),
            ("P2 xpass Sage Occidental != INSUFFICIENT_INFO", [
                (lambda r: r and r.get("status") != "INSUFFICIENT_INFORMATION")(find(run, "occidental")) for run in alt]),
            ("P2 xpass Sage Wilshire != INSUFFICIENT_INFO", [
                (lambda r: r and r.get("status") != "INSUFFICIENT_INFORMATION")(find(run, "wilshire")) for run in alt]),
            ("P2 xpass Progressive HO3 surfaces solar", [
                "solar" in blob(find(run, "progressive", "ho3", exclude=("ho6",)), "missing_info", "citations")
                for run in alt]),
            ("P3 Allied Trust 14yr roof != ELIGIBLE (was 67%)", [
                (lambda r: r and r.get("status") != "ELIGIBLE")(find(run, "allied trust")) for run in alt]),
            ("P3 Mercury no spurious PPC10 question (hard assert)", [
                ("ppc 10" not in blob(find(run, "mercury"), "missing_info")
                 and "ppc-10" not in blob(find(run, "mercury"), "missing_info")) for run in alt]),
            ("P5 Allied Trust NOT declined over solar", [
                (lambda r: r and not (r.get("status") == "INELIGIBLE"
                                      and "solar" in blob(r, "reasons", "citations")))(find(run, "allied trust"))
                for run in alt]),
            ("xfail TWICO circuit panel question surfaced", [
                "circuit panel" in blob(find(run, "twico"), "missing_info") for run in alt]),
            ("xfail TWICO fire dept response time surfaced", [
                ("response time" in blob(find(run, "twico"), "missing_info")
                 or "fire department" in blob(find(run, "twico"), "missing_info")) for run in alt]),
        ])

    print(f"\nRuns analyzed: STANDARD={len(std)}  ALT={len(alt)}")


if __name__ == "__main__":
    main()
