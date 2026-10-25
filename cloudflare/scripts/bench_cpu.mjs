// CPU per request for every /api route, against the Workers Free plan's 10 ms CPU limit (round 43 step 3).
//
// usage (cwd = the repo root):
//   node cloudflare/scripts/bench_cpu.mjs [--cases cloudflare/build/parity_cases.json] [--csv-dir rules_data/placement]
//        [--n 2000] [--blocks 5] [--usage-rows 20000] [--feedback-rows 1000] [--only "admin"]
//
// Each route runs as the Worker's own fetch() on real Request objects (built before the clock starts), with an Access
// token verified on every request (RS256 against a cached test JWKS) and env.DB the node:sqlite D1 stand-in loaded
// with a year of synthetic usage / feedback rows. Round 44b: the placement tables are the Worker's bundled module,
// built from the CSVs first (loadWorker), so the placement routes read no D1 in either measurement. Windows' process CPU clock ticks
// every ~15.6 ms, so a request is never timed alone: process.cpuUsage() over a block of N requests, divided by N.
// Two measurements per route: A with D1 = node:sqlite in this process (SQLite's work counted too -- an upper bound),
// B with D1's answers replayed as JSON (CannedDb below) -- the Worker's own CPU, which is what the 10 ms limit counts.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { resetJwksCache } from "../src/access.js";
import { DEFAULT_CSV_DIR, loadWorker, makeAccess, makeDb, makeEnv, req } from "./harness.mjs";
import { sqlLit } from "./lib.mjs";
import { feedbackCsvLine } from "../src/csv.js";

const args = process.argv.slice(2);
const opt = (name, d) => { const i = args.indexOf(name); return i < 0 ? d : args[i + 1]; };
const N = parseInt(opt("--n", "2000"), 10), BLOCKS = parseInt(opt("--blocks", "5"), 10);
const csvDir = resolve(opt("--csv-dir", process.env.PLACEMENT_CSV_DIR || DEFAULT_CSV_DIR));
const casesFile = opt("--cases", null);
const ONLY = opt("--only", "");
const USAGE_ROWS = parseInt(opt("--usage-rows", "20000"), 10), FEEDBACK_ROWS = parseInt(opt("--feedback-rows", "1000"), 10);

function syntheticLogs() {
  const start = Date.UTC(2025, 9, 24);
  const iso = (ms) => new Date(ms).toISOString().slice(0, 19) + "+00:00";
  const u = [], f = [];
  for (let i = 0; i < USAGE_ROWS; i++) {
    const t = iso(start + Math.floor((i / USAGE_ROWS) * 365 * 86400000));
    u.push(`(${[t, "agent" + (i % 12) + "@cfigtx.com", t, "abc1234", 1.2, 41, '{"engine_s":0.8,"render_s":0.3}'].map(sqlLit).join(",")})`);
  }
  const pd = JSON.stringify({ zip: "77494", county: "Fort Bend", year_built: 1994, dwelling_amount: 350000, occupancy_type: "Owner Occupied",
    roof_type: "Composition Shingle", roof_age: 14, swimming_pool: "No Pool", dog_breeds: [], ppc: "3" });
  for (let i = 0; i < FEEDBACK_ROWS; i++) {
    const t = iso(start + Math.floor((i / FEEDBACK_ROWS) * 365 * 86400000));
    const row = { received_at: t, email: "agent@cfigtx.com", ts: t, app_version: "abc1234", name: "Jo", property_details: pd,
      carrier: "Mercury_HO3_-_01.01.2026", display_name: "Mercury HO3", verdict: "INELIGIBLE",
      reasons: JSON.stringify(["[MER-029] declines: Plumbing must be copper, PVC or PEX.", "[MER-031] roof, older than 15 years"]),
      deciding_rows: '["MER-029","MER-031"]', model: "", rules_table: 1, checked_topics: '["plumbing","roof"]',
      choice: "Should be Eligible", comment: "The plumbing is copper, per the inspection." };
    row.csv_row = feedbackCsvLine(row);
    f.push(`(${Object.values(row).map(sqlLit).join(",")})`);
  }
  const chunk = (rows, head) => { const out = []; for (let i = 0; i < rows.length; i += 500) out.push(head + rows.slice(i, i + 500).join(",") + ";"); return out; };
  return [...chunk(u, "INSERT INTO usage (received_at, email, ts, app_version, wall_s, carriers, timings) VALUES "),
    ...chunk(f, "INSERT INTO feedback (received_at, email, ts, app_version, name, property_details, carrier, display_name, "
      + "verdict, reasons, deciding_rows, model, rules_table, checked_topics, choice, comment, csv_row) VALUES ")];
}

function placementBodies() {
  if (casesFile) {
    const cases = JSON.parse(readFileSync(casesFile, "utf8")).filter((c) => c.variant === "golden");
    return {
      panel: cases.filter((c) => c.expected).slice(0, 500).map((c) => ({ pd: c.pd, results: c.results, as_of: c.as_of })),
      none: cases.filter((c) => !c.expected).slice(0, 500).map((c) => ({ pd: c.pd, results: c.results, as_of: c.as_of })),
    };
  }
  const fx = JSON.parse(readFileSync(new URL("../test/fixtures/placement_cases.json", import.meta.url), "utf8"));
  return { panel: fx.filter((c) => c.expected).map((c) => c.body), none: fx.filter((c) => !c.expected).map((c) => c.body) };
}

const A = await makeAccess();
globalThis.fetch = A.fetchStub;
resetJwksCache();
const { worker } = await loadWorker(csvDir);
const db = makeDb(syntheticLogs());
const env = makeEnv(db);
const agent = await A.token(), admin = await A.token({ email: "liam@cfigtx.com" });
const bodies = placementBodies();
const usageBody = { ts: "2026-10-24T18:00:00+00:00", app_version: "abc1234", wall_s: 1.234, carriers: 41,
  timings: { engine_s: 0.81, render_s: 0.2, placement_s: 0.05 } };
const feedbackBody = { ts: "2026-10-24T18:01:00+00:00", app_version: "abc1234", name: "Jo",
  property_details: JSON.parse(readFileSync(new URL("../test/fixtures/feedback_log.jsonl", import.meta.url), "utf8").split("\n")[0]).property_details,
  carrier: "TWICO_HO3", display_name: "TWICO HO3", verdict: "INELIGIBLE", reasons: ["[TWI-001] Roof older than 15 years: declines."],
  deciding_rows: ["TWI-001"], model: "", rules_table: true, checked_topics: null, choice: "Should be Eligible", comment: "Roof is 9 years old." };

const ROUTES = [
  ["GET /api/whoami", (i) => req("/api/whoami", { token: agent })],
  ["POST /api/usage", (i) => req("/api/usage", { method: "POST", token: agent, body: usageBody })],
  ["POST /api/feedback", (i) => req("/api/feedback", { method: "POST", token: agent, body: feedbackBody })],
  [`POST /api/placement (panel; ${bodies.panel.length} real check bodies)`, (i) => req("/api/placement", { method: "POST", token: agent, body: bodies.panel[i % bodies.panel.length] })],
  [`POST /api/placement (null; ${bodies.none.length} bodies)`, (i) => req("/api/placement", { method: "POST", token: agent, body: bodies.none[i % bodies.none.length] })],
  ["GET /api/admin/weekly", (i) => req("/api/admin/weekly", { token: admin })],
  ["GET /api/admin/feedback.csv", (i) => req("/api/admin/feedback.csv", { token: admin })],
  ["GET /api/whoami, no token (401)", (i) => req("/api/whoami")],
];

const ms = (u) => (u.user + u.system) / 1000;

async function block(make, n, e = env) {
  const reqs = Array.from({ length: n }, (_, i) => make(i));
  const c0 = process.cpuUsage(), w0 = performance.now();
  let bad = 0;
  for (const r of reqs) {
    const res = await worker.fetch(r, e, {});
    if (res.status >= 500) bad++;
  }
  const cpu = ms(process.cpuUsage(c0)) / n, wall = (performance.now() - w0) / n;
  return { cpu, wall, bad };
}

// D1 as the Worker sees it in production: the query runs elsewhere and its answer arrives as JSON. CannedDb answers
// every statement from the JSON of the real answer (computed once, in the warm-up), parsed fresh each time; a write is
// acknowledged without running. Its blocks are the Worker's own CPU: token, body, logic, result parsing, response.
class CannedDb {
  constructor(real) { this.real = real; this.cache = new Map(); }
  async answer(key, compute) {
    let j = this.cache.get(key);
    if (j === undefined) { j = JSON.stringify(await compute()); this.cache.set(key, j); }
    return JSON.parse(j);
  }
  prepare(sql) { return new CannedStmt(this, sql, []); }
  async batch(stmts) {
    return this.answer(stmts.map((x) => x.key()).join(" ;; "), () => this.real.batch(stmts.map((x) => x.realStmt())));
  }
}
class CannedStmt {
  constructor(db, sql, params) { this.db = db; this.sql = sql; this.params = params; }
  bind(...p) { return new CannedStmt(this.db, this.sql, p); }
  key() { return this.sql + JSON.stringify(this.params); }
  realStmt() { return this.db.real.prepare(this.sql).bind(...this.params); }
  async all() { return this.db.answer(this.key(), () => this.realStmt().all()); }
  async first(c) { return this.db.answer(this.key() + "#first" + c, () => this.realStmt().first(c)); }
  async run() { return { success: true, results: [], meta: { changes: 1, last_row_id: 1 } }; }
}
const cannedEnv = makeEnv(new CannedDb(db));

console.log(`node ${process.version}, ${N} requests a block, ${BLOCKS} blocks; usage rows ${USAGE_ROWS}, feedback rows ${FEEDBACK_ROWS}`);
console.log("route | A: CPU ms/req, D1 = node:sqlite in-process (blocks) | A median | B: Worker CPU ms/req, D1 answers parsed from JSON (blocks) | B median");
for (const [name, make] of ROUTES) {
  if (ONLY && !name.includes(ONLY)) continue;
  const out = [];
  for (const e of [env, cannedEnv]) {
    await block(make, Math.max(600, Math.min(300, N)), e);      // warm-up: JIT, statement cache, JWKS, every canned answer
    const res = [];
    for (let b = 0; b < BLOCKS; b++) res.push(await block(make, N, e));
    const cpus = res.map((r) => r.cpu).sort((x, y) => x - y);
    out.push(res.map((r) => r.cpu.toFixed(3)).join(", "), cpus[Math.floor(cpus.length / 2)].toFixed(3));
    if (res.some((r) => r.bad)) out.push(`(${res.reduce((t, r) => t + r.bad, 0)} 5xx!)`);
  }
  console.log(`${name} | ${out.join(" | ")}`);
}
const t0 = process.cpuUsage();
const { verifyAccessJwt } = await import("../src/access.js");
for (let i = 0; i < N; i++) await verifyAccessJwt(agent, { teamDomain: "cfig-test.cloudflareaccess.com", aud: "test-aud-0123456789abcdef" });
console.log(`(Access JWT verification alone: ${(ms(process.cpuUsage(t0)) / N).toFixed(3)} ms/request)`);
