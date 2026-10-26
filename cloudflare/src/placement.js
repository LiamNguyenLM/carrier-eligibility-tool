// The placement panel, answered by the Worker (round 43 step 3).
//
// A line-for-line port of placement.py's panel() and everything it calls (markets_in, candidates, rank,
// nearby, fit_line, _compact, _pct), reading only the rows one panel needs from the tables bundled into the
// Worker (round 44b; they were in D1 until the load blew the free tier) instead of load_tables()'s whole CSVs.
// panel_markdown() is NOT ported: the browser builds the markdown itself (Python in Pyodide) from the dict returned
// here.
//
// Python behaviour kept on purpose (each one is checked by cloudflare/scripts/placement_parity.mjs):
//   * round() is round-half-even (_pct: 1 of 8 is "12%", not "13%");
//   * str.split()/strip() whitespace is Python's set (PY_WS), not JS's \s;
//   * _compact cuts by code points, not UTF-16 units;
//   * every sort is Python's (stable, code-point order), every weighted sum is taken in the CSV's row
//     order and every "sum(d.values())" in the dict's insertion order (Map here).
// One deliberate difference: placement.py's statewide mix T["all"] is every placement_zip row; the bundled tables
// hold it summed per (month, market) (as D1's placement_all did). The weights are the same; the floating-point sums
// can differ in the last bit, which can only matter for two scores equal to ~1e-16 -- the parity check counts it.

export const HALF_LIFE = 4.0, WINDOW_MONTHS = 36, K_ZIP = 15.0, K_COUNTY = 30.0, MIN_DIM = 20.0;
export const AGE = [[10, 20, 30, 40, 60], ["0-9", "10-19", "20-29", "30-39", "40-59", "60+"]];
export const COVA = [[200000, 300000, 400000, 600000, 1000000],
  ["<200K", "200-299K", "300-399K", "400-599K", "600-999K", "1M+"]];
export const CANDIDATE_STATUSES = new Set(["ELIGIBLE", "INSUFFICIENT_INFORMATION"]);

export const TITLE = "Where we usually place homes like this";
const FOOTER = (through) => `From our HawkSoft placements through ${through}. Where we have placed similar homes, `
  + "not a price comparison.";
export const STATEWIDE = "Few recent sales nearby; ranked mostly on our statewide mix";
const NONE_NEARBY = (market, area) => `No recent sales with ${market} in ${area}; ranked on our statewide mix`;
export const LANDLORD_BASIS = "Based on our homeowners placements; we don't have enough landlord history yet.";
export const LANDLORD_OCCUPANCIES = new Set(["Tenant Occupied", "Vacant"]);
const RECENT_MONTHS = 12, MIN_NEARBY = 10, MIN_BAND = 10, MIN_BAND_OWN = 5, FIT_LIFT = 1.25;
const AGE_WORDS = { "60+": "60-plus-year-old" };
const COVA_WORDS = { "<200K": "under-$200K", "1M+": "$1M-plus" };
const STATUS_ORDER = { ELIGIBLE: 0, INSUFFICIENT_INFORMATION: 1 };
const RULED_OUT_ORDER = { INELIGIBLE: 0, REFER: 1 };

// ------------------------------------------------------------------------------------------ Python helpers
// Python's str.isspace() set (what str.split() and str.strip() with no argument use).
const PY_WS = "\\t\\n\\x0b\\x0c\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const WS_RUN = new RegExp(`[${PY_WS}]+`, "g");
const WS_LEAD = new RegExp(`^[${PY_WS}]+`);
const WS_TRAIL = new RegExp(`[${PY_WS}]+$`);
const SURROGATE = /[\uD800-\uDFFF]/;

export const pyStrip = (s) => s.replace(WS_LEAD, "").replace(WS_TRAIL, "");
const pyRstrip = (s) => s.replace(WS_TRAIL, "");
const pySplitJoin = (s) => s.split(WS_RUN).filter((x) => x !== "").join(" ");

/** Python's string order (code points); JS's < is UTF-16 units, which differs only past U+FFFF. */
export function pyCmp(a, b) {
  if (a === b) return 0;
  if (!SURROGATE.test(a) && !SURROGATE.test(b)) return a < b ? -1 : 1;
  const x = Array.from(a, (c) => c.codePointAt(0)), y = Array.from(b, (c) => c.codePointAt(0));
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1;
  return x.length - y.length;
}

/** Python's round(x) for x >= 0: half to even. */
function pyRound(x) {
  const f = Math.floor(x), d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

export const countyKey = (county) => pyStrip(county || "").toLowerCase();

export function monthIndex(ym) {
  const [y, m] = ym.split("-");
  return parseInt(y, 10) * 12 + parseInt(m, 10) - 1;
}

/** The current month in America/Chicago (the agency's clock), "YYYY-MM". */
export function currentMonth(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", year: "numeric", month: "2-digit" })
    .formatToParts(now);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get("year")}-${get("month")}`;
}

export function band(value, spec) {
  if (value === null || value === undefined) return "";
  const [edges, labels] = spec;
  for (let i = 0; i < edges.length; i++) if (value < edges[i]) return labels[i];
  return labels[labels.length - 1];
}

export const ageBand = (year, yearBuilt) => (yearBuilt ? band(year - yearBuilt, AGE) : "");
export const covaBand = (covA) => (covA && covA >= 20000 ? band(covA, COVA) : "");

// ------------------------------------------------------------------------------------------ the data
const NO_ROWS = Object.freeze([]);

/** One key's rows (a ZIP, a county key, a band) -- an own property only, so a county typed as "constructor" or
 * "__proto__" finds no rows instead of Object.prototype's. */
const own = (o, k) => (o && Object.hasOwn(o, k) ? o[k] : NO_ROWS);

/** [[mi, market, n], ...] for the flat rows with mi in [lo, hi], in their CSV order. */
function windowRows(flat, names, lo, hi) {
  const out = [];
  for (let i = 0; i < flat.length; i += 3) {
    const mi = flat[i];
    if (mi >= lo && mi <= hi) out.push([mi, names[flat[i + 1]], flat[i + 2]]);
  }
  return out;
}

/**
 * Every row one panel can use, from the tables bundled into the Worker (cloudflare/scripts/build_placement.mjs; round
 * 44b, they left D1): the markets and data_through, and the 36 whole months before as_of of the statewide mix, the
 * ZIP, the county and the home's two profile bands. Returns the same shapes placement.load_tables() builds,
 * restricted to those keys and months -- what the D1 batch returned before.
 */
export function loadPanelTables(data, { zip5, county, ageB, covaB, asof }) {
  const lo = asof - WINDOW_MONTHS, hi = asof - 1;
  const rows = (flat) => windowRows(flat, data.names, lo, hi);
  const band = (dim, val) => (val ? rows(own(own(data.profile, dim), val)) : []);
  return {
    markets: data.markets,
    meta: { data_through: data.meta.data_through },
    all: rows(data.all),
    zip: zip5 ? rows(own(data.zip, zip5)) : [],
    county: rows(own(data.county, countyKey(county))),
    profile: { age_band: band("age_band", ageB), covA_band: band("covA_band", covaB) },
  };
}

// ------------------------------------------------------------------------------------------ the port
function marketOf(program, markets) {
  const p = typeof program === "string" ? program : "";
  for (const [prefix, m] of markets) if (p.startsWith(prefix)) return m;
  return null;
}

/** {market: [records]} (a Map, in first-seen order) for every record that maps to a market. */
export function marketsIn(results, markets) {
  const out = new Map();
  for (const r of results) {
    const m = marketOf(r.carrier, markets);
    if (m) {
      if (!out.has(m)) out.set(m, []);
      out.get(m).push(r);
    }
  }
  return out;
}

export function candidates(byMarket) {
  const out = [];
  for (const [m, recs] of byMarket) if (recs.some((r) => CANDIDATE_STATUSES.has(r.status))) out.push(m);
  return out.sort(pyCmp);
}

/** placement._weighted: a Map in insertion order, like the Python defaultdict. */
function weighted(entries, asof, cands) {
  const w = new Map();
  for (const [mi, m, n] of entries) {
    const ago = asof - mi;
    if (cands.has(m) && ago >= 1 && ago <= WINDOW_MONTHS) w.set(m, (w.get(m) ?? 0) + n * 0.5 ** (ago / HALF_LIFE));
  }
  return w;
}

function sumValues(map) {
  let s = 0;
  for (const v of map.values()) s += v;
  return s;
}

/** placement.rank: [[market, score], ...] best first. */
export function rank(T, candidateMarkets, zip5, county, yearBuilt, covA, asOf, year) {
  const cands = new Set(candidateMarkets);
  if (!cands.size) return [];
  const asof = monthIndex(asOf);
  year = year || parseInt(asOf.slice(0, 4), 10);
  const K = cands.size;
  const wa = weighted(T.all, asof, cands);
  const tot = sumValues(wa);
  const g = new Map(), cty = new Map(), z = new Map(), score = new Map();
  for (const m of cands) g.set(m, ((wa.get(m) ?? 0) + 0.5) / (tot + 0.5 * K));
  const wc = weighted(T.county, asof, cands);
  const nc = sumValues(wc);
  for (const m of cands) cty.set(m, ((wc.get(m) ?? 0) + K_COUNTY * g.get(m)) / (nc + K_COUNTY));
  const wz = weighted(T.zip, asof, cands);
  const nz = sumValues(wz);
  for (const m of cands) z.set(m, ((wz.get(m) ?? 0) + K_ZIP * cty.get(m)) / (nz + K_ZIP));
  for (const m of cands) score.set(m, Math.log(z.get(m)));
  const bands = [["age_band", ageBand(year, yearBuilt)], ["covA_band", covaBand(covA)]];
  for (const [dim, val] of bands) {
    if (!val) continue;
    const wd = weighted(T.profile[dim], asof, cands);
    const nd = sumValues(wd);
    if (nd < MIN_DIM) continue;
    for (const m of cands) {
      const s = ((wd.get(m) ?? 0) + 5 * g.get(m)) / (nd + 5);
      score.set(m, score.get(m) + Math.log(s / g.get(m)));
    }
  }
  return [...score.entries()].sort((a, b) => (b[1] - a[1]) || pyCmp(a[0], b[0]));
}

/** placement._recent: unweighted sales per market in the 12 whole months before as_of. */
function recent(entries, asof, months = RECENT_MONTHS) {
  const c = new Map();
  for (const [mi, m, n] of entries) {
    const ago = asof - mi;
    if (ago >= 1 && ago <= months) c.set(m, (c.get(m) ?? 0) + n);
  }
  return c;
}

function nearby(T, zip5, county, asof) {
  const z = recent(T.zip, asof);
  if (zip5 && sumValues(z) >= MIN_NEARBY) return [`ZIP ${zip5}`, z];
  const name = pyStrip(county || "");
  const c = recent(T.county, asof);
  if (name && sumValues(c) >= MIN_NEARBY) return [`${name} County`, c];
  return [null, new Map()];
}

const pct = (a, b) => `${pyRound((100 * a) / b)}%`;

function bandWords(dim, val) {
  if (dim === "age_band") return (AGE_WORDS[val] ?? val) + (val in AGE_WORDS ? "" : "-year-old");
  return (COVA_WORDS[val] ?? "$" + val) + " Coverage A";
}

function fitLine(T, market, yearBuilt, covA, asof, year) {
  const overall = recent(T.all, asof);
  const total = sumValues(overall);
  if (!total || !overall.get(market)) return null;
  const base = overall.get(market) / total;
  let best = null;
  for (const [dim, val] of [["age_band", ageBand(year, yearBuilt)], ["covA_band", covaBand(covA)]]) {
    if (!val) continue;
    const b = recent(T.profile[dim], asof);
    const n = sumValues(b);
    if (n < MIN_BAND) continue;
    const own = b.get(market) ?? 0;
    const share = own / n;
    if (own >= MIN_BAND_OWN && share >= FIT_LIFT * base) {
      const line = [share / base, `${pct(own, n)} of our ${bandWords(dim, val)} homes vs ${pct(overall.get(market), total)} overall`];
      // max(lines): the larger lift, then (a tie) the larger text
      if (!best || line[0] > best[0] || (line[0] === best[0] && pyCmp(line[1], best[1]) > 0)) best = line;
    }
  }
  return best ? best[1] : null;
}

function compact(text, limit = 110) {
  const t = pySplitJoin(text || "");
  const cps = Array.from(t);
  return cps.length <= limit ? t : pyRstrip(cps.slice(0, limit - 1).join("")) + "…";
}

const firstString = (list) => (Array.isArray(list) ? list.filter((x) => typeof x === "string" && pyStrip(x)) : []);

/**
 * placement.panel(): the panel's content, or null when it is not shown (fewer than 2 candidate markets).
 * T: loadPanelTables()'s tables, or any object of the same shape (the parity check passes the D1 stand-in's).
 */
export function buildPanel(results, pd, asOf, T) {
  const year = parseInt(asOf.slice(0, 4), 10);
  const asof = monthIndex(asOf);
  const byMarket = marketsIn(results, T.markets);
  const cands = candidates(byMarket);
  if (cands.length < 2) return null;
  const zip5 = pd.zip || "", county = pd.county || "";
  const yearBuilt = pd.year_built ?? null, covA = pd.dwelling_amount ?? null;
  const order = rank(T, cands, zip5, county, yearBuilt, covA, asOf, year).slice(0, 3).map(([m]) => m);
  const [where, sales] = nearby(T, zip5, county, asof);
  const total = sumValues(sales);
  const picks = [];
  for (const m of order) {
    const recs = byMarket.get(m).filter((r) => CANDIDATE_STATUSES.has(r.status))
      .sort((a, b) => (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || pyCmp(a.carrier || "", b.carrier || ""));
    let held = null;
    if (recs[0].status !== "ELIGIBLE") {
      const items = firstString(recs[0].missing_info);
      held = "Held: confirm " + (items.length ? compact(items[0], 90) : "the open items on its card");
    }
    let reason;
    if (!where) reason = STATEWIDE;
    else if (!sales.get(m)) reason = NONE_NEARBY(m, where);
    else reason = `Our homeowners sales in ${where}: ${sales.get(m)} of ${total} with ${m} (${pct(sales.get(m), total)})`;
    picks.push({ market: m, programs: recs.map((r) => r.carrier), held, reason,
      fit: fitLine(T, m, yearBuilt, covA, asof, year) });
  }
  let usual = null;
  if (where && sales.size) {
    const top = [...sales.entries()].sort((a, b) => (b[1] - a[1]) || pyCmp(a[0], b[0]))[0][0];
    if (byMarket.has(top) && !cands.includes(top)) {
      const out = [...byMarket.get(top)].sort((a, b) =>
        ((RULED_OUT_ORDER[a.status] ?? 2) - (RULED_OUT_ORDER[b.status] ?? 2)) || pyCmp(a.carrier || "", b.carrier || ""));
      let first = "";
      for (const r of out) {
        const f = firstString(r.reasons);
        if (f.length) { first = f[0]; break; }
      }
      usual = `Usually ${top} here (${sales.get(top)} of ${total}); not for this home: `
        + (compact(first) || (out[0].status || "").replaceAll("_", " ").toLowerCase());
    }
  }
  const basis = LANDLORD_OCCUPANCIES.has(pd.occupancy_type) ? LANDLORD_BASIS : null;
  return { title: TITLE, basis, picks, usual, footer: FOOTER(T.meta.data_through ?? "?") };
}

// ------------------------------------------------------------------------------------------ the request
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const STR_OR_NULL = (v) => v === null || v === undefined || typeof v === "string";
const NUM_OR_NULL = (v) => v === null || v === undefined || (typeof v === "number" && Number.isFinite(v));

/** The POST /api/placement body checked and reduced to what panel() reads; throws a message on a bad body. */
export function parsePlacementBody(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("body must be a JSON object");
  const pd = body.pd ?? {};
  if (typeof pd !== "object" || Array.isArray(pd)) throw new Error("pd must be an object");
  for (const k of ["zip", "county", "occupancy_type"]) if (!STR_OR_NULL(pd[k])) throw new Error(`pd.${k} must be a string or null`);
  for (const k of ["year_built", "dwelling_amount"]) if (!NUM_OR_NULL(pd[k])) throw new Error(`pd.${k} must be a number or null`);
  if (!Array.isArray(body.results) || body.results.length > 200) throw new Error("results must be a list (at most 200)");
  const results = body.results.map((r, i) => {
    if (!r || typeof r !== "object") throw new Error(`results[${i}] must be an object`);
    if (typeof r.carrier !== "string" || typeof r.status !== "string") throw new Error(`results[${i}] needs carrier and status strings`);
    for (const k of ["missing_info", "reasons"]) {
      if (r[k] !== undefined && r[k] !== null && !Array.isArray(r[k])) throw new Error(`results[${i}].${k} must be a list`);
    }
    // only the first non-blank string of each list is ever read; the rest is dropped here
    return { carrier: r.carrier, status: r.status, missing_info: firstString(r.missing_info).slice(0, 1),
      reasons: firstString(r.reasons).slice(0, 1) };
  });
  let asOf = body.as_of;
  if (asOf === undefined || asOf === null || asOf === "") asOf = currentMonth();
  else if (typeof asOf !== "string" || !MONTH.test(asOf)) throw new Error("as_of must be YYYY-MM");
  const p = { zip: pd.zip ?? "", county: pd.county ?? "", year_built: pd.year_built ?? null,
    dwelling_amount: pd.dwelling_amount ?? null, occupancy_type: pd.occupancy_type ?? null };
  return { pd: p, results, asOf };
}

/** POST /api/placement's answer: panel() or null, from the bundled tables (`data`, build_placement.mjs). */
export function placementPanel(data, body) {
  const { pd, results, asOf } = parsePlacementBody(body);
  const year = parseInt(asOf.slice(0, 4), 10);
  const T = loadPanelTables(data, { zip5: pd.zip, county: pd.county, ageB: ageBand(year, pd.year_built),
    covaB: covaBand(pd.dwelling_amount), asof: monthIndex(asOf) });
  return buildPanel(results, pd, asOf, T);
}
