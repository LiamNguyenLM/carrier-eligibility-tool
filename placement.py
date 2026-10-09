"""Where we usually place homes like this (Liam, 2026-10-09; round 33).

Ranks the carrier markets the eligibility check did NOT rule out, using the agency's own HawkSoft
placement history (monthly counts by ZIP, county, home-age band and Coverage A band, per market:
rules_data/placement/, refreshed monthly by Claude). It never changes a verdict. Off unless
ELIGIBILITY_PLACEMENT is exactly "1".

rank() is the reference scorer (pilot_structured_rules/placement/placement_score.py, Claude,
2026-10-09; a verbatim copy is verification/placement_score_reference.py) and must rank identically:
  * only whole months BEFORE as_of count, within WINDOW_MONTHS; a month's counts are weighted
    0.5 ** (months_ago / HALF_LIFE), the month just before as_of being months_ago = 1;
  * g[m]   = (W_all[m] + 0.5) / (W_total + 0.5 * K) over the K candidate markets;
  * cty[m] = (W_county[m] + K_COUNTY * g[m]) / (W_county_total + K_COUNTY);
  * z[m]   = (W_zip[m] + K_ZIP * cty[m]) / (W_zip_total + K_ZIP);
  * for the home's age band and Coverage A band, when known and the band's weighted total over the
    candidates is >= MIN_DIM: score += log(((W_dim[m] + 5 g[m]) / (W_dim_total + 5)) / g[m]);
  * score[m] = log(z[m]) + those terms; order: score desc, then market name.
Backtest (Claude, 300 homes sold Apr-Oct 2026, history before Apr 2026): the market we actually
used was in the top 3 of the not-ruled-out markets for 132 of 210 homes (63%).
"""
import csv
import datetime
import functools
import math
import os
from collections import defaultdict

HALF_LIFE, WINDOW_MONTHS, K_ZIP, K_COUNTY, MIN_DIM = 4.0, 36, 15.0, 30.0, 20.0
AGE = ([10, 20, 30, 40, 60], ["0-9", "10-19", "20-29", "30-39", "40-59", "60+"])
COVA = ([200000, 300000, 400000, 600000, 1000000], ["<200K", "200-299K", "300-399K", "400-599K", "600-999K", "1M+"])
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules_data", "placement")
# A market is a candidate when any of its programs came back one of these (Eligible, or held).
CANDIDATE_STATUSES = frozenset({"ELIGIBLE", "INSUFFICIENT_INFORMATION"})


def enabled():
    return os.environ.get("ELIGIBILITY_PLACEMENT", "") == "1"


def current_month(today=None):
    today = today or datetime.date.today()
    return f"{today.year:04d}-{today.month:02d}"


def band(value, spec):
    if value is None:
        return ""
    for edge, label in zip(*spec):
        if value < edge:
            return label
    return spec[1][-1]


def month_index(ym):
    y, m = ym.split("-")
    return int(y) * 12 + int(m) - 1


@functools.lru_cache(maxsize=None)
def load_tables(data_dir=DATA_DIR):
    """The tables, read once per directory."""
    def rows(name):
        with open(os.path.join(data_dir, name), encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    T = {"zip": defaultdict(list), "county": defaultdict(list), "profile": defaultdict(list), "all": []}
    for r in rows("placement_zip.csv"):
        mi, n = month_index(r["month"]), int(r["n"])
        T["zip"][r["zip"]].append((mi, r["market"], n))
        T["all"].append((mi, r["market"], n))
    for r in rows("placement_county.csv"):
        T["county"][r["county"]].append((month_index(r["month"]), r["market"], int(r["n"])))
    for r in rows("placement_profile.csv"):
        T["profile"][(r["dim"], r["value"])].append((month_index(r["month"]), r["market"], int(r["n"])))
    T["markets"] = [(r["program_prefix"], r["market"]) for r in rows("placement_markets.csv")]
    T["meta"] = {r["key"]: r["value"] for r in rows("placement_meta.csv")}
    return T


def market_of(program, T=None):
    """The market a program belongs to (the first prefix that matches), or None."""
    T = T or load_tables()
    return next((m for prefix, m in T["markets"] if (program or "").startswith(prefix)), None)


def markets_in(results, T=None):
    """{market: [records]} for every record of the check that maps to a market."""
    T = T or load_tables()
    out = defaultdict(list)
    for r in results:
        m = market_of(r.get("carrier"), T)
        if m:
            out[m].append(r)
    return dict(out)


def candidates(results, T=None):
    """Markets the check did not rule out: any of their programs came back Eligible or held
    (Insufficient Information). Every other status (Ineligible, Refer, closed, guide unavailable,
    not evaluated) rules a market out only when none of its programs is a candidate."""
    return sorted(m for m, recs in markets_in(results, T).items()
                  if any(r.get("status") in CANDIDATE_STATUSES for r in recs))


def _weighted(entries, asof, cands):
    w = defaultdict(float)
    for mi, m, n in entries:
        ago = asof - mi
        if m in cands and 1 <= ago <= WINDOW_MONTHS:
            w[m] += n * 0.5 ** (ago / HALF_LIFE)
    return w


def rank(T, candidate_markets, zip5, county, year_built, cov_a, as_of, year=None):
    """[(market, score), ...], best first, over candidate_markets. Identical to the reference."""
    cands = set(candidate_markets)
    if not cands:
        return []
    asof = month_index(as_of)
    year = year or int(as_of[:4])
    K = len(cands)
    wa = _weighted(T["all"], asof, cands)
    tot = sum(wa.values())
    g = {m: (wa[m] + 0.5) / (tot + 0.5 * K) for m in cands}
    wc = _weighted(T["county"].get((county or "").strip().title(), []), asof, cands)
    nc = sum(wc.values())
    cty = {m: (wc[m] + K_COUNTY * g[m]) / (nc + K_COUNTY) for m in cands}
    wz = _weighted(T["zip"].get(zip5 or "", []), asof, cands)
    nz = sum(wz.values())
    z = {m: (wz[m] + K_ZIP * cty[m]) / (nz + K_ZIP) for m in cands}
    score = {m: math.log(z[m]) for m in cands}
    bands = {"age_band": band(year - year_built, AGE) if year_built else "",
             "covA_band": band(cov_a, COVA) if cov_a and cov_a >= 20000 else ""}
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


# --------------------------------------------------------------------------- the panel (round 33 step 2)
TITLE = "Where we usually place homes like this"
FOOTER = ("From our HawkSoft placements through {through}. Where we have placed similar homes, "
          "not a price comparison.")
STATEWIDE = "Few recent sales nearby; ranked mostly on our statewide mix"
RECENT_MONTHS, MIN_NEARBY, MIN_BAND, FIT_LIFT = 12, 10, 10, 1.25
_AGE_WORDS = {"60+": "60-plus-year-old"}       # else "10-19" -> "10-19-year-old"
_COVA_WORDS = {"<200K": "under-$200K", "1M+": "$1M-plus"}


def _recent(entries, asof, months=RECENT_MONTHS):
    """Unweighted sales per market in the `months` whole months before as_of (all markets)."""
    c = defaultdict(int)
    for mi, m, n in entries:
        if 1 <= asof - mi <= months:
            c[m] += n
    return c


def nearby(T, zip5, county, asof):
    """(label, {market: sales}) for the last 12 months: the ZIP when it had at least 10 sales, else
    the county when it had at least 10, else (None, {})."""
    z = _recent(T["zip"].get(zip5 or "", []), asof)
    if zip5 and sum(z.values()) >= MIN_NEARBY:
        return f"ZIP {zip5}", z
    name = (county or "").strip().title()
    c = _recent(T["county"].get(name, []), asof)
    if name and sum(c.values()) >= MIN_NEARBY:
        return f"{name} County", c
    return None, {}


def _pct(a, b):
    return f"{round(100 * a / b)}%"


def fit_line(T, market, year_built, cov_a, asof, year):
    """The home's age or Coverage A band when the market is a strong fit there (last 12 months: its
    share of the band >= 1.25x its overall share, the band holding at least 10 sales); else None.
    With both, the larger lift."""
    overall = _recent(T["all"], asof)
    total = sum(overall.values())
    if not total or not overall.get(market):
        return None
    base = overall[market] / total
    lines = []
    bands = (("age_band", band(year - year_built, AGE) if year_built else ""),
             ("covA_band", band(cov_a, COVA) if cov_a and cov_a >= 20000 else ""))
    for dim, val in bands:
        if not val:
            continue
        b = _recent(T["profile"].get((dim, val), []), asof)
        n = sum(b.values())
        if n < MIN_BAND:
            continue
        share = b.get(market, 0) / n
        if share >= FIT_LIFT * base:
            lines.append((share / base, f"{_pct(b.get(market, 0), n)} of our {_band_words(dim, val)} homes "
                                        f"vs {_pct(overall[market], total)} overall"))
    return max(lines)[1] if lines else None


def _band_words(dim, val):
    if dim == "age_band":
        return _AGE_WORDS.get(val, val) + ("" if val in _AGE_WORDS else "-year-old")
    return _COVA_WORDS.get(val, "$" + val) + " Coverage A"


def _compact(text, limit=110):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


_STATUS_ORDER = {"ELIGIBLE": 0, "INSUFFICIENT_INFORMATION": 1}
_RULED_OUT_ORDER = {"INELIGIBLE": 0, "REFER": 1}


def panel(results, property_details, as_of=None, T=None, year=None):
    """The panel's content, or None when it is not shown (fewer than 2 candidate markets). Never
    changes a record."""
    T = T or load_tables()
    as_of = as_of or current_month()
    year = year or int(as_of[:4])
    asof = month_index(as_of)
    by_market = markets_in(results, T)
    cands = candidates(results, T)
    if len(cands) < 2:
        return None
    pd = property_details or {}
    zip5, county = pd.get("zip") or "", pd.get("county") or ""
    year_built = pd.get("year_built")
    cov_a = pd.get("dwelling_amount")
    order = [m for m, _ in rank(T, cands, zip5, county, year_built, cov_a, as_of, year=year)][:3]
    where, sales = nearby(T, zip5, county, asof)
    total = sum(sales.values())
    picks = []
    for m in order:
        recs = sorted((r for r in by_market[m] if r.get("status") in CANDIDATE_STATUSES),
                      key=lambda r: (_STATUS_ORDER[r["status"]], r.get("carrier", "")))
        held = None
        if recs[0]["status"] != "ELIGIBLE":
            items = [x for x in recs[0].get("missing_info") or [] if isinstance(x, str) and x.strip()]
            held = "Held: confirm " + (_compact(items[0], 90) if items else "the open items on its card")
        reason = (f"Our homeowners sales in {where}: {sales.get(m, 0)} of {total} with {m} "
                  f"({_pct(sales.get(m, 0), total)})") if where else STATEWIDE
        picks.append({"market": m, "programs": [r["carrier"] for r in recs], "held": held, "reason": reason,
                      "fit": fit_line(T, m, year_built, cov_a, asof, year)})
    usual = None
    if where and sales:
        top = sorted(sales.items(), key=lambda x: (-x[1], x[0]))[0][0]
        if top in by_market and top not in cands:
            out = sorted(by_market[top], key=lambda r: (_RULED_OUT_ORDER.get(r.get("status"), 2), r.get("carrier", "")))
            first = next((x for r in out for x in (r.get("reasons") or []) if str(x).strip()), "")
            usual = (f"Usually {top} here ({sales[top]} of {total}); not for this home: "
                     f"{_compact(first) or out[0].get('status', '').replace('_', ' ').lower()}")
    return {"title": TITLE, "picks": picks, "usual": usual,
            "footer": FOOTER.format(through=T["meta"].get("data_through", "?"))}


def panel_markdown(p):
    """The panel as one markdown block (the footer is shown separately, small)."""
    lines = [f"#### {p['title']}"]
    for i, pick in enumerate(p["picks"], 1):
        lines.append(f"{i}. **{pick['market']}** — {', '.join(pick['programs'])}")
        for extra in (pick["held"], pick["reason"], pick["fit"]):
            if extra:
                lines.append(f"    - {extra}")
    if p["usual"]:
        lines.append("")
        lines.append(p["usual"])
    return "\n".join(lines)


def status_line(T=None):
    """The Database Fingerprint line: on or off, and the data's month and size."""
    try:
        T = T or load_tables()
        data = f"data through {T['meta'].get('data_through', '?')}, {int(T['meta'].get('policies', 0)):,} policies"
    except Exception as exc:                     # noqa: BLE001 -- the panel line never breaks the page
        data = f"tables unreadable ({type(exc).__name__})"
    return f"Placement panel: {'ON' if enabled() else 'OFF'} ({data})"
