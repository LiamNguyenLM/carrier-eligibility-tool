// The Worker's routes end to end in Node (round 43 step 3): node --test cloudflare/test/
// Zero network: D1 is node:sqlite (scripts/lib.mjs), Access is a test key pair (scripts/harness.mjs).
// PLACEMENT_CSV_DIR overrides rules_data/placement (the drafts directory has no repo around it).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { before, test } from "node:test";
import { fileURLToPath } from "node:url";
import worker from "../src/worker.js";
import { resetJwksCache } from "../src/access.js";
import { isoWeek } from "../src/routes.js";
import { DEFAULT_CSV_DIR, makeAccess, makeDb, makeEnv, req } from "../scripts/harness.mjs";
import { buildImportSql } from "../scripts/import_logs.mjs";
import { parseCsv } from "../scripts/lib.mjs";

const FIX = join(dirname(fileURLToPath(import.meta.url)), "fixtures");
const CSV_DIR = process.env.PLACEMENT_CSV_DIR || DEFAULT_CSV_DIR;
let A, env, db, agent, liam;
const call = (r, e = env) => worker.fetch(r, e, {});

before(async () => {
  A = await makeAccess();
  globalThis.fetch = A.fetchStub;
  resetJwksCache();
  const { sql } = buildImportSql({ feedback: join(FIX, "feedback_log.jsonl"), usage: join(FIX, "usage_log.jsonl") });
  db = makeDb(CSV_DIR, [sql, sql]);                         // imported twice: must not duplicate
  env = makeEnv(db);
  agent = await A.token();
  liam = await A.token({ email: "Liam@CFIGtx.com" });
});

// ------------------------------------------------------------------------------------------------ Access
test("every /api route needs a valid Access token", async () => {
  for (const [m, p] of [["GET", "/api/whoami"], ["POST", "/api/usage"], ["POST", "/api/feedback"], ["POST", "/api/placement"],
    ["GET", "/api/admin/feedback.csv"], ["GET", "/api/admin/weekly"], ["GET", "/api/nope"]]) {
    const r = await call(req(p, { method: m, body: m === "POST" ? {} : undefined }));
    assert.equal(r.status, 401, `${m} ${p}`);
  }
});

test("whoami: the verified email, lower-cased, and admin from ADMIN_EMAILS", async () => {
  // CHANGED (round 44 step 1, Liam 2026-10-25: the password gate): + name, mode and the logout link, which the page
  // uses; Access mode's email and admin answers are as before.
  const extra = { name: "", mode: "access", logout: "/cdn-cgi/access/logout" };
  assert.deepEqual(await (await call(req("/api/whoami", { token: agent }))).json(), { email: "agent@cfigtx.com", admin: false, ...extra });
  assert.deepEqual(await (await call(req("/api/whoami", { token: liam }))).json(), { email: "liam@cfigtx.com", admin: true, ...extra });
});

test("a bad token is refused: signature, audience, issuer, expiry, nbf, algorithm, no email", async () => {
  const now = Math.floor(Date.now() / 1000);
  const cases = {
    "bad signature": [await A.token({}, { key: await A.otherKey() }), 401],
    "wrong audience": [await A.token({ aud: ["someone-else"] }), 401],
    "aud as a string, wrong": [await A.token({ aud: "someone-else" }), 401],
    "wrong issuer": [await A.token({ iss: "https://evil.cloudflareaccess.com" }), 401],
    expired: [await A.token({ exp: now - 120 }), 401],
    "not yet valid": [await A.token({ nbf: now + 600 }), 401],
    "alg none": [await A.token({}, { header: { alg: "none" } }), 401],
    "unknown kid": [await A.token({}, { header: { kid: "other" } }), 401],
    "service token (no email)": [await A.token({ email: undefined, common_name: "svc" }), 403],
    garbage: ["abc.def", 401],
  };
  for (const [name, [tok, status]] of Object.entries(cases)) {
    const r = await call(req("/api/whoami", { token: tok }));
    assert.equal(r.status, status, name);
  }
  assert.equal((await call(req("/api/whoami", { token: await A.token({ aud: "test-aud-0123456789abcdef" }) }))).status, 200);
});

test("the JWKS is fetched once and cached", async () => {
  resetJwksCache();
  const before_ = A.fetches();
  for (let i = 0; i < 5; i++) await call(req("/api/whoami", { token: agent }));
  assert.equal(A.fetches() - before_, 1);
});

test("DEV_AUTH_EMAIL works only on plain http to localhost", async () => {
  const dev = makeEnv(db, { DEV_AUTH_EMAIL: "liam@cfigtx.com" });
  for (const base of ["http://localhost:8787", "http://127.0.0.1:8787", "http://[::1]:8787"]) {
    const r = await call(req("/api/whoami", { base }), dev);
    assert.equal(r.status, 200, base);
  }
  for (const base of ["https://localhost:8787", "https://eligibility.cfigtx.com", "http://eligibility.cfigtx.com",
    "http://localhost.evil.com", "http://127.0.0.1.nip.io"]) {
    assert.equal((await call(req("/api/whoami", { base }), dev)).status, 401, base);
  }
  assert.equal((await call(req("/api/whoami", { base: "http://localhost:8787" }))).status, 401, "no var, no bypass");
});

test("Access not configured fails closed (500), not open", async () => {
  const r = await call(req("/api/whoami", { token: agent }), makeEnv(db, { ACCESS_AUD: "" }));
  assert.equal(r.status, 500);
  // round 43 step 3: wrangler.toml's shipped placeholders count as not configured (the first deploy has them)
  for (const ACCESS_AUD of ["REPLACE-WITH-THE-ACCESS-APPLICATION-AUD-TAG", "TBD"]) {
    const p = await call(req("/api/whoami", { token: agent }), makeEnv(db, { ACCESS_AUD }));
    assert.equal(p.status, 500, ACCESS_AUD);
  }
});

// ------------------------------------------------------------------------------------------------ usage
test("POST /api/usage stores one row with the email; model '' and cost 0", async () => {
  const body = { ts: "2026-10-24T18:00:00+00:00", app_version: "abc1234", wall_s: 1.234, carriers: 41,
    timings: { engine_s: 0.8123, render_s: 0.2, placement_s: 0.05 } };
  const r = await call(req("/api/usage", { method: "POST", token: agent, body }));
  assert.equal(r.status, 201);
  const { id } = await r.json();
  const row = db.sqlite.prepare("SELECT * FROM usage WHERE id = ?").get(id);
  assert.equal(row.email, "agent@cfigtx.com");
  assert.equal(row.model, "");
  assert.equal(row.cost, 0);
  assert.equal(row.wall_s, 1.23);
  assert.equal(row.carriers, 41);
  assert.deepEqual(JSON.parse(row.timings), { engine_s: 0.81, render_s: 0.2, placement_s: 0.05 });
  assert.equal(row.source, "worker");
});

test("POST /api/usage refuses > 16 KB, non-JSON content types and bad fields", async () => {
  const big = { ts: "2026-10-24T18:00:00+00:00", pad: "x".repeat(17 * 1024) };
  assert.equal((await call(req("/api/usage", { method: "POST", token: agent, body: big }))).status, 413);
  assert.equal((await call(req("/api/usage", { method: "POST", token: agent, body: "{}", type: "text/plain" }))).status, 415);
  assert.equal((await call(req("/api/usage", { method: "POST", token: agent, body: "{nope" }))).status, 400);
  assert.equal((await call(req("/api/usage", { method: "POST", token: agent, body: { carriers: "41" } }))).status, 400);
  assert.equal((await call(req("/api/usage", { method: "POST", token: agent, body: { timings: { a: "slow" } } }))).status, 400);
  assert.equal((await call(req("/api/usage", { method: "GET", token: agent }))).status, 405);
});

// ------------------------------------------------------------------------------------------------ feedback
test("POST /api/feedback: feedback.record()'s fields, choice outside CHOICES becomes Not sure, > 64 KB refused", async () => {
  const body = { ts: "2026-10-24T18:01:00+00:00", app_version: "abc1234", name: "  Jo  ", property_details: { zip: "77494" },
    carrier: "TWICO_HO3", display_name: "TWICO HO3", verdict: "INELIGIBLE", reasons: ["[TWI-001] x"],
    deciding_rows: ["TWI-001"], model: "", rules_table: true, checked_topics: null, choice: "Should be Maybe",
    comment: "  wrong  " };
  const r = await call(req("/api/feedback", { method: "POST", token: agent, body }));
  assert.equal(r.status, 201);
  const row = db.sqlite.prepare("SELECT * FROM feedback WHERE id = ?").get((await r.json()).id);
  assert.equal(row.choice, "Not sure");
  assert.equal(row.name, "Jo");
  assert.equal(row.comment, "wrong");
  assert.equal(row.email, "agent@cfigtx.com");
  assert.equal(row.checked_topics, null);
  assert.equal(row.rules_table, 1);
  assert.ok(row.csv_row.startsWith("2026-10-24T18:01:00+00:00,abc1234,Jo,TWICO_HO3,TWICO HO3,INELIGIBLE,Not sure,wrong,"));
  assert.ok(row.csv_row.endsWith(',True,,"{""zip"": ""77494""}",agent@cfigtx.com'));
  const big = { ...body, comment: "x".repeat(65 * 1024) };
  assert.equal((await call(req("/api/feedback", { method: "POST", token: agent, body: big }))).status, 413);
  assert.equal((await call(req("/api/feedback", { method: "POST", token: agent, body: { property_details: [] } }))).status, 400);
  db.sqlite.prepare("DELETE FROM feedback WHERE source = 'worker'").run();     // keep the CSV test to the imports
});

// ------------------------------------------------------------------------------------------------ placement
test("POST /api/placement answers exactly what placement.panel() does (fixtures from Python)", async () => {
  const cases = JSON.parse(readFileSync(join(FIX, "placement_cases.json"), "utf8"));
  for (const c of cases) {
    const r = await call(req("/api/placement", { method: "POST", token: agent, body: c.body }));
    assert.equal(r.status, 200, c.name);
    assert.equal(await r.text(), JSON.stringify(c.expected), c.name);
  }
});

test("POST /api/placement refuses a bad body", async () => {
  const ok = { pd: { zip: "77494" }, results: [] };
  for (const bad of [{ ...ok, as_of: "2026-13" }, { ...ok, pd: { zip: 77494 } }, { ...ok, pd: { year_built: "1994" } },
    { ...ok, results: [{ carrier: 1, status: "ELIGIBLE" }] }, { pd: {}, results: "x" }]) {
    assert.equal((await call(req("/api/placement", { method: "POST", token: agent, body: bad }))).status, 400, JSON.stringify(bad));
  }
  assert.equal(await (await call(req("/api/placement", { method: "POST", token: agent, body: ok }))).text(), "null");
});

test("POST /api/placement says 503 when D1 is unavailable", async () => {
  const broken = makeEnv({ prepare: db.prepare.bind(db), batch: async () => { throw new Error("D1_ERROR: database is importing"); } });
  const cases = JSON.parse(readFileSync(join(FIX, "placement_cases.json"), "utf8"));
  assert.equal((await call(req("/api/placement", { method: "POST", token: agent, body: cases[0].body }), broken)).status, 503);
});

// ------------------------------------------------------------------------------------------------ admin
test("admin routes are admins only", async () => {
  assert.equal((await call(req("/api/admin/feedback.csv", { token: agent }))).status, 403);
  assert.equal((await call(req("/api/admin/weekly", { token: agent }))).status, 403);
});

test("feedback.csv: feedback.to_csv()'s bytes for the imported lines, with email added last", async () => {
  const r = await call(req("/api/admin/feedback.csv", { token: liam }));
  assert.equal(r.status, 200);
  const got = await r.text();
  const want = readFileSync(join(FIX, "feedback_expected.csv"), "utf8");    // Python's, imported twice -> once
  // Python's CSV ends every row with ",<email>" here (email is ''): strip the last column and compare bytes
  const stripped = got.split("\r\n").map((line, i) => (line === "" ? line : i === 0 ? line.replace(/,email$/, "") : line.replace(/,$/, ""))).join("\r\n");
  assert.equal(stripped, want);
  // multi-line fields: parse to be sure the rows are whole
  assert.equal(parseCsv(got).length, 3);
});

test("weekly: checks and reports per ISO week, imports included once", async () => {
  const r = await call(req("/api/admin/weekly", { token: liam }));
  const w = await r.json();
  const by = Object.fromEntries(w.weeks.map((x) => [x.week, x]));
  // usage fixtures: 10-12 (W42), 10-20 (W43), 10-25 (W43, a Sunday); plus the row the usage test posted (now)
  assert.equal(by["2026-W42"].checks, 1);
  assert.ok(by["2026-W43"].checks >= 2);
  // feedback fixtures: 10-19 and 10-21 (W43), 10-26 (W44, a Monday)
  assert.equal(by["2026-W43"].feedback, 2);
  assert.equal(by["2026-W44"].feedback, 1);
  assert.equal(by["2026-W44"].start, "2026-10-26");
});

test("isoWeek handles the year edges", () => {
  assert.deepEqual(isoWeek("2026-01-01"), { week: "2026-W01", start: "2025-12-29" });
  assert.deepEqual(isoWeek("2027-01-01"), { week: "2026-W53", start: "2026-12-28" });
  assert.deepEqual(isoWeek("2024-12-30"), { week: "2025-W01", start: "2024-12-30" });
});

test("import_logs: re-running inserts nothing new", () => {
  const n = (t) => db.sqlite.prepare(`SELECT count(*) AS n FROM ${t} WHERE source = 'railway'`).get().n;
  assert.equal(n("feedback"), 3);
  assert.equal(n("usage"), 3);
});

test("static paths go to ASSETS", async () => {
  assert.equal(await (await call(req("/index.html"))).text(), "asset");
});

test("feedback.csv keeps (ts, id) order across D1's 400-line chunks", async () => {
  const ins = db.sqlite.prepare("INSERT INTO feedback (received_at, ts, csv_row, source) VALUES (?, ?, ?, 'test')");
  const tss = [];
  for (let i = 0; i < 950; i++) {
    const ts = `2027-0${1 + (i * 7919) % 9}-${String(1 + (i * 104729) % 28).padStart(2, "0")}T00:00:00+00:00`;
    tss.push(ts);
    ins.run(ts, ts, `${ts},row`);
  }
  // round 43 step 3: 300 reports a part -- every part, in order, is the whole file; the header only in part 1
  const first = await call(req("/api/admin/feedback.csv", { token: liam }));
  const parts = Number(first.headers.get("x-feedback-parts"));
  assert.equal(parts, Math.ceil((950 + 3) / 300));
  let text = await first.text();
  for (let p = 2; p <= parts; p++) {
    const t = await (await call(req(`/api/admin/feedback.csv?part=${p}`, { token: liam }))).text();
    assert.ok(!t.startsWith("ts,"), `part ${p} repeats the header`);
    text += t;
  }
  assert.equal(text.split("\r\n").filter((l) => l.startsWith("ts,")).length, 1);
  const lines = text.split("\r\n").filter((l) => l.endsWith(",row"));
  assert.deepEqual(lines, tss.map((t) => `${t},row`).sort());      // equal ts: insertion (id) order, which sort() keeps here
  db.sqlite.prepare("DELETE FROM feedback WHERE source = 'test'").run();
});
