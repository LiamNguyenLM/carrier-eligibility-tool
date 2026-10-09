"""Reference scorer for the placement panel (Claude, 2026-10-09). Stdlib only.

rank(tables, candidates, zip, county, year_built, cov_a, as_of="YYYY-MM", year=None) ->
    [(market, score), ...] best first, over `candidates` (markets the check did not rule out).

Model (backtested on 300 homes sold Apr-Oct 2026 with history before Apr 2026: the carrier we
actually used was in the top 3 of the not-ruled-out carriers 63% of the time, vs 52% for
"our most-used carriers lately" and 16% random):
  * Only months BEFORE as_of count, within WINDOW_MONTHS; each month's counts are weighted
    0.5 ** (months_ago / HALF_LIFE), months_ago = whole months from that month to as_of
    (the month just before as_of has months_ago = 1).
  * g[m]  = (W_all[m] + 0.5) / (W_total + 0.5 * K), over the K candidate markets only.
  * cty[m] = (W_county[m] + K_COUNTY * g[m]) / (W_county_total + K_COUNTY)
  * z[m]   = (W_zip[m] + K_ZIP * cty[m]) / (W_zip_total + K_ZIP)
  * for dim in (age_band, covA_band), if the home's band is known and the band's weighted
    total over the candidates is >= MIN_DIM:
        s[m] = (W_dim[m] + 5 * g[m]) / (W_dim_total + 5);  score += log(s[m] / g[m])
  * score[m] = log(z[m]) + those terms.
  * County lookup is case-insensitive ("McLennan" = "Mclennan" = "MCLENNAN"; Claude 2026-10-09).
"""
import csv, math, os
from collections import defaultdict

HALF_LIFE, WINDOW_MONTHS, K_ZIP, K_COUNTY, MIN_DIM = 4.0, 36, 15.0, 30.0, 20.0
AGE = ([10, 20, 30, 40, 60], ["0-9", "10-19", "20-29", "30-39", "40-59", "60+"])
COVA = ([200000, 300000, 400000, 600000, 1000000], ["<200K", "200-299K", "300-399K", "400-599K", "600-999K", "1M+"])


def _band(v, spec):
    if v is None:
        return ""
    for e, l in zip(*spec):
        if v < e:
            return l
    return spec[1][-1]


def _mi(ym):
    y, m = ym.split("-")
    return int(y) * 12 + int(m) - 1


def load_tables(d):
    T = {"zip": defaultdict(list), "county": defaultdict(list), "profile": defaultdict(list), "all": []}
    for r in csv.DictReader(open(os.path.join(d, "placement_zip.csv"), encoding="utf-8")):
        mi, n = _mi(r["month"]), int(r["n"])
        T["zip"][r["zip"]].append((mi, r["market"], n))
        T["all"].append((mi, r["market"], n))
    for r in csv.DictReader(open(os.path.join(d, "placement_county.csv"), encoding="utf-8")):
        T["county"][r["county"].strip().lower()].append((_mi(r["month"]), r["market"], int(r["n"])))
    for r in csv.DictReader(open(os.path.join(d, "placement_profile.csv"), encoding="utf-8")):
        T["profile"][(r["dim"], r["value"])].append((_mi(r["month"]), r["market"], int(r["n"])))
    return T


def _weighted(entries, asof, cands):
    w = defaultdict(float)
    for mi, m, n in entries:
        ago = asof - mi
        if m in cands and 1 <= ago <= WINDOW_MONTHS:
            w[m] += n * 0.5 ** (ago / HALF_LIFE)
    return w


def rank(T, candidates, zip5, county, year_built, cov_a, as_of, year=None):
    cands = set(candidates)
    if not cands:
        return []
    asof = _mi(as_of)
    year = year or int(as_of[:4])
    K = len(cands)
    wa = _weighted(T["all"], asof, cands)
    tot = sum(wa.values())
    g = {m: (wa[m] + 0.5) / (tot + 0.5 * K) for m in cands}
    wc = _weighted(T["county"].get((county or "").strip().lower(), []), asof, cands)
    nc = sum(wc.values())
    cty = {m: (wc[m] + K_COUNTY * g[m]) / (nc + K_COUNTY) for m in cands}
    wz = _weighted(T["zip"].get(zip5 or "", []), asof, cands)
    nz = sum(wz.values())
    z = {m: (wz[m] + K_ZIP * cty[m]) / (nz + K_ZIP) for m in cands}
    score = {m: math.log(z[m]) for m in cands}
    bands = {"age_band": _band(year - year_built, AGE) if year_built else "",
             "covA_band": _band(cov_a, COVA) if cov_a and cov_a >= 20000 else ""}
    for dim, val in bands.items():
        if not val:
            continue
        wd = _weighted(T["profile"].get((dim, val), []), asof, cands)
        nd = sum(wd.values())
        if nd < MIN_DIM:
            continue
        for m in cands:
            s = (wd[m] + 5 * g[m]) / (nd + 5)
            score[m] += math.log(s / g[m])
    return sorted(score.items(), key=lambda x: (-x[1], x[0]))
