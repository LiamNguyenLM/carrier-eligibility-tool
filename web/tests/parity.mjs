#!/usr/bin/env node
// Round 43 step 2 (Liam, 2026-10-24): the page's parity harness (Playwright, the installed Microsoft Edge; no
// browser download). It serves web/dist with a stand-in for the Worker's /api routes.
//
//   node web/tests/parity.mjs --profiles <[{id, pd, checked}] json> [--dist web/dist]
//        (the list: `python verification/parity/export_golden.py inputs verification/parity/golden.json.xz out.json`;
//         the candidate is compared with the golden by web/tests/candidate_to_golden.py)
//            --limit N  --skip-form  --skip-check  --loads N (first-load timing runs, default 3)
//            --out <candidate.json> (default tests/out/candidate_<mode>.json)  --headed
//
// (a) form: for every profile, fillForm(pd, checked) through the widgets' DOM events, submit(), and compare
//     lastForm() with the profile (every differing key, and why).
// (b) check: runCheck(pd, checked) for every profile the engine can answer, read every card back from the DOM
//     (data-carrier / data-status / data-column and the card's <script class="card-raw">) plus the top box, and
//     write the candidate (JSONL, one {id, pd, checked, top_box, cards} a line); web/tests/candidate_to_golden.py compares it
//     with the golden.
// Also: first-load time, per-check engine and render time, and one "This looks wrong" report sent through the form.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { startServer } from "../tools/serve.mjs";

const WEB = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const argv = process.argv.slice(2);
const flag = (k) => argv.includes(k);
const opt = (k, d) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : d);

const MODE = "engine";
const DIST = path.resolve(WEB, opt("--dist", "dist"));
const QUERY = "";
const LIMIT = Number(opt("--limit", 0)) || Infinity;
const LOADS = Number(opt("--loads", 3));
const OUT = path.resolve(WEB, opt("--out", `tests/out/candidate_${MODE}.json`));
const TEXT_KEYS = ["carrier", "status", "name", "first", "missing", "confirm_html", "details_html", "ids_html",
                   "warning"];
const RECORD_KEYS = ["raw_status", "flaw_count", "reasons", "citations", "notes", "also_confirm", "confirm_items",
                     "missing_info", "deciding_rows", "rules_table"];
const COLS = ["eligible", "refer", "insufficient_info", "not_eligible", "could_not_check"];
// Round 44: --base <url> runs against a server that is already up (npx wrangler dev: the real Worker, its password
// gate and local D1) instead of tools/serve.mjs; --password signs in on its login page in every fresh browser
// context (or HARNESS_PASSWORD, to keep it off the command line). The page's own POSTs are captured either way.
const BASE = opt("--base", null);
const PASSWORD = opt("--password", process.env.HARNESS_PASSWORD || null);
const captured = [];                         // {path, body} of every POST the page sends

const sortKeys = (v) => (Array.isArray(v) ? v.map(sortKeys) : v && typeof v === "object"
  ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys(v[k])])) : v);
const eq = (a, b) => JSON.stringify(sortKeys(a ?? null)) === JSON.stringify(sortKeys(b ?? null));
const stats = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * s.length))];
  return s.length ? { n: s.length, mean: s.reduce((x, y) => x + y, 0) / s.length, median: q(0.5), p95: q(0.95),
                      max: s[s.length - 1] } : { n: 0 };
};
const fmt = (st) => (st.n ? `n=${st.n} mean ${(st.mean * 1000).toFixed(1)} ms, median ${(st.median * 1000).toFixed(1)}`
  + ` ms, p95 ${(st.p95 * 1000).toFixed(1)} ms, max ${(st.max * 1000).toFixed(1)} ms` : "n=0");

const external = [];

async function openPage(browser, base, errors) {
  const ctx = await browser.newContext();                  // a fresh context: empty cache, a true first load
  // nothing leaves localhost: any other request is aborted and reported
  await ctx.route("**/*", (route) => {
    const r = route.request();
    const u = r.url();
    if (u.startsWith(base)) {
      if (r.method() === "POST" && new URL(u).pathname.startsWith("/api/")) {
        try { captured.push({ path: new URL(u).pathname, body: r.postDataJSON() }); } catch { /* not JSON */ }
      }
      return route.continue();
    }
    external.push(u);
    return route.abort();
  });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
  if (PASSWORD) {                              // round 44: through the gate's login page, as an agent would
    await page.goto(base + "/login");
    await page.fill('input[name="password"]', PASSWORD);
    await page.fill('input[name="name"]', "Parity Harness");
    await Promise.all([page.waitForURL(base + "/"), page.click('button[type="submit"]')]);
  }
  const requests = [];                         // every request this page load sends to the site (round 44)
  page.on("request", (r) => { if (r.url().startsWith(base)) requests.push(new URL(r.url()).pathname); });
  const t0 = Date.now();
  await page.goto(base + QUERY);
  await page.waitForFunction(() => window.__eligibility && (window.__eligibility.ready || window.__eligibility.error),
                             null, { timeout: 180000 });
  const wall = (Date.now() - t0) / 1000;
  const err = await page.evaluate(() => window.__eligibility.error);
  if (err) throw new Error("page did not load: " + err);
  const lt = await page.evaluate(() => window.__eligibility.loadTimings());
  await page.waitForTimeout(300);              // let whoami settle before counting
  return { ctx, page, wall, lt: { ...lt, requests: requests.length, request_paths: [...requests] } };
}

function formDiff(profile, form, notes) {
  const diffs = [];
  const pd = profile.pd;
  const got = form.property_details;
  if (!got) return { diffs: [{ key: "*", kind: "error", why: form.error }], checked: "not built" };
  const why = (k) => notes.filter((n) => n.key === k).map((n) => n.why).join("; ");
  for (const k of new Set([...Object.keys(pd), ...Object.keys(got)])) {
    const inP = k in pd;
    const inF = k in got;
    if (inP && inF && eq(pd[k], got[k])) continue;
    if (inP && !inF) diffs.push({ key: k, kind: "profile has it, the form does not send it", why: why(k) || "the form "
      + "sends this key only when its question is shown and answered", profile: pd[k] });
    else if (!inP) diffs.push({ key: k, kind: "the form sends it, the profile does not have it",
      why: why(k) || "the form always sends this key when its question is on screen", form: got[k] });
    else diffs.push({ key: k, kind: "different value", why: why(k) || "the form's reading of the widget differs",
      profile: pd[k], form: got[k] });
  }
  for (const n of notes) {
    if (n.key === "checked" || (!diffs.some((d) => d.key === n.key) && !(n.key in got) && !(n.key in pd))) {
      diffs.push({ key: n.key, kind: "note", why: n.why });
    }
  }
  const want = profile.checked;
  const have = form.checked_topics;
  let checked;
  if (eq(want, have)) checked = "exact";
  else if (want == null) checked = have.length === 13 ? "profile None (every topic); the form sends the full list"
    : "profile None; the form sends a partial list";
  else if (eq([...want].sort(), [...have].sort())) checked = "same topics, different order (the form lists them in "
    + "topics.TOPIC_KEYS order)";
  else checked = "different topics";
  return { diffs, checked };
}

// profile ids grouped as the golden names them (fuzz_, HARTFORD_DEEP_, R40_DEEP_, HARTFORD_, the rest): "n of m"
function groupIds(ids, profiles) {
  const g = (id) => (/^(fuzz|HARTFORD_DEEP|R40_DEEP|HARTFORD)_/.exec(id) || [null, "named"])[1];
  const out = {};
  for (const p of profiles) (out[g(p.id)] ||= [0, 0])[1]++;
  for (const id of ids) out[g(id)][0]++;
  return Object.fromEntries(Object.entries(out).map(([k, [a, b]]) => [k, `${a} of ${b}`]));
}

async function partForm(page, profiles, report) {
  const byKind = new Map();
  const checkedKinds = new Map();
  let exactPd = 0;
  let fully = 0;
  const fillTimes = [];
  const notExpressible = [];
  for (const p of profiles) {
    const t0 = Date.now();
    const r = await page.evaluate(async ({ pd, checked }) => {
      const h = window.__eligibility;
      const filled = await h.fillForm(pd, checked);
      await h.submit();
      return { notes: filled.notes, form: h.lastForm() };
    }, { pd: p.pd, checked: p.checked });
    fillTimes.push((Date.now() - t0) / 1000);
    const { diffs, checked } = formDiff(p, r.form, r.notes);
    const pdDiffs = diffs.filter((d) => d.kind !== "note");
    if (!pdDiffs.length) exactPd++;
    if (!pdDiffs.length && (checked === "exact" || checked.startsWith("same topics")
        || checked.startsWith("profile None (every topic)"))) fully++;
    else notExpressible.push(p.id);
    checkedKinds.set(checked, (checkedKinds.get(checked) || 0) + 1);
    for (const d of diffs) {
      const k = `${d.key} | ${d.kind} | ${d.why}`;
      if (!byKind.has(k)) byKind.set(k, { key: d.key, kind: d.kind, why: d.why, count: 0, examples: [] });
      const e = byKind.get(k);
      e.count++;
      if (e.examples.length < 3) e.examples.push({ id: p.id, profile: d.profile, form: d.form });
    }
  }
  report.form = {
    profiles: profiles.length, pd_equal: exactPd, expressible: fully,
    expressible_note: "pd equal key by key (order ignored) and the same checked topics (order ignored, None = all)",
    checked: Object.fromEntries(checkedKinds),
    differences: [...byKind.values()].sort((a, b) => b.count - a.count),
    fill_and_submit_s: stats(fillTimes),
    not_expressible_by_group: groupIds(notExpressible, profiles),
    not_expressible: notExpressible,
  };
}

async function partCheck(page, profiles, expected, report) {
  // the candidate is written as it goes, one profile per line (JSONL): all 3,569 at once is longer than a JS string
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  const outFd = fs.openSync(OUT, "w");
  let nCards = 0;
  const diffs = [];
  const engineT = [];
  const renderT = [];
  let placementShown = 0;
  let skipped = 0;
  for (const p of profiles) {
    // pd_json (export_golden.py inputs): the profile as Python's JSON text, passed through untouched, as the page's
    // own submit passes form_request's text -- a JS copy of the pd would turn a whole-number 9.0 into 9
    const r = await page.evaluate(async ({ pd, pdJson, checked }) => {
      const h = window.__eligibility;
      const run = pdJson ? await h.runCheckJson(pdJson, checked) : await h.runCheck(pd, checked);
      if (!run.ok) return { run };
      const pl = await h.placementSettled();
      return { run, dom: h.readResults(), result: h.lastResult(), timings: h.lastTimings(), pl };
    }, { pd: p.pd, pdJson: p.pd_json || null, checked: p.checked });
    if (!r.run.ok) {
      skipped++;
      diffs.push({ id: p.id, what: "check failed", detail: r.run.error });
      continue;
    }
    engineT.push(r.timings.engine_s);
    renderT.push(r.timings.render_s);
    if (r.dom.placement_shown) placementShown++;
    const res = r.result;
    const colOf = {};
    for (const c of COLS) for (const i of res.columns[c] || []) colOf[i] = c;
    const domByIndex = new Map(r.dom.cards.map((c) => [c.index, c]));
    const cards = res.cards.map((card, i) => {
      const d = domByIndex.get(i);
      if (!d) { diffs.push({ id: p.id, carrier: card.carrier, what: "card not on the page" }); return null; }
      if (d.column !== d.in_column) diffs.push({ id: p.id, carrier: d.carrier, what: "data-column vs the column it "
        + "sits in", detail: [d.column, d.in_column] });
      if (d.column !== colOf[i]) diffs.push({ id: p.id, carrier: d.carrier, what: "column", detail: [colOf[i], d.column] });
      if (d.carrier !== d.raw_carrier) diffs.push({ id: p.id, carrier: d.carrier, what: "data-carrier vs card-raw" });
      const out = { carrier: d.carrier, status: d.status, column: d.column };
      for (const k of TEXT_KEYS.slice(2)) out[k] = d[k];
      out.record = Object.fromEntries(RECORD_KEYS.map((k) => [k, card[k]]));
      return out;
    }).filter(Boolean);
    fs.writeSync(outFd, JSON.stringify({ id: p.id, pd: p.pd, checked: p.checked, top_box: r.dom.top_box, cards }) + "\n");
    nCards += cards.length;
    const exp = expected && expected.get(p.id);
    if (exp) {
      if (!eq(exp.top_box, r.dom.top_box)) diffs.push({ id: p.id, what: "top_box" });
      if (exp.cards.length !== cards.length) diffs.push({ id: p.id, what: "card count", detail: [exp.cards.length, cards.length] });
      const expCol = {};
      for (const c of COLS) for (const i of exp.columns[c] || []) expCol[i] = c;
      exp.cards.forEach((e, i) => {
        const c = cards[i];
        if (!c) return;
        for (const k of TEXT_KEYS) if (!eq(e[k], c[k])) diffs.push({ id: p.id, carrier: e.carrier, what: k, detail: [e[k], c[k]] });
        if (expCol[i] !== c.column) diffs.push({ id: p.id, carrier: e.carrier, what: "column", detail: [expCol[i], c.column] });
      });
    }
  }
  fs.closeSync(outFd);
  report.check = {
    profiles: profiles.length, checked: profiles.length - skipped, cards: nCards,
    compared_with_fixtures: !!expected, differences: diffs.length, first_differences: diffs.slice(0, 20),
    engine_s: stats(engineT), render_s: stats(renderT), placement_panel_shown: placementShown, candidate: OUT,
  };
}

async function feedbackRoundTrip(page, server, report) {
  // one "This looks wrong" report through the real controls
  const card = page.locator("details.card").first();
  if (!(await card.count())) { report.feedback = "no card on the page"; return; }
  await card.locator("summary").first().click();
  const fb = card.locator("details.feedback");
  await fb.locator("summary").click();
  await fb.locator("input[type=radio]").first().check();
  await fb.locator("textarea").fill("  parity harness test  ");
  await fb.locator("button[type=submit]").click();
  await fb.locator(".sent").waitFor({ state: "visible", timeout: 5000 });
  const posts = (server.posts.length ? server.posts : captured).filter((p) => p.path === "/api/feedback");
  const rec = posts[posts.length - 1]?.body;
  const want = ["ts", "app_version", "name", "property_details", "carrier", "display_name", "verdict", "reasons",
                "deciding_rows", "model", "rules_table", "checked_topics", "choice", "comment"];
  const build = JSON.parse(fs.readFileSync(path.join(DIST, "build.json"), "utf8"));
  const problems = [];
  if (!rec) problems.push("no POST /api/feedback");
  else {
    if (!eq(Object.keys(rec), want)) problems.push("keys " + JSON.stringify(Object.keys(rec)));
    if (rec.model !== "") problems.push("model " + rec.model);
    if (rec.comment !== "parity harness test") problems.push("comment not stripped: " + JSON.stringify(rec.comment));
    if (rec.choice !== "Should be Eligible") problems.push("choice " + rec.choice);
    if (rec.app_version !== build.commit) problems.push("app_version " + rec.app_version + " vs " + build.commit);
    if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$/.test(rec.ts)) problems.push("ts " + rec.ts);
  }
  const formReset = await fb.locator("textarea").inputValue();
  if (formReset !== "") problems.push("comment box not cleared after Send");
  report.feedback = problems.length ? { ok: false, problems } : { ok: true, record_keys: want.length };
}

async function main() {
  if (!fs.existsSync(path.join(DIST, "index.html"))) {
    console.error(`no build at ${DIST}: run npm run build first`);
    process.exit(2);
  }
  const server = BASE ? { url: BASE.replace(/\/$/, ""), posts: [], close() {} }
    : await startServer({ dir: DIST, mockApi: true });
  const browser = await chromium.launch({ channel: "msedge", headless: !flag("--headed") });
  const errors = [];
  const report = { mode: MODE, dist: DIST, url: server.url + QUERY, loads: [] };
  try {
    let session = null;
    for (let i = 0; i < LOADS; i++) {
      const s = await openPage(browser, server.url, errors);
      report.loads.push({ wall_s: s.wall, ...s.lt });
      if (i < LOADS - 1) await s.ctx.close();
      else session = s;
    }
    const { page } = session;
    const expected = null;
    if (!opt("--profiles")) { console.error("--profiles <file> is needed"); process.exit(2); }
    let profiles = JSON.parse(fs.readFileSync(path.resolve(opt("--profiles")), "utf8"));
    profiles = profiles.slice(0, LIMIT);
    if (opt("--ids")) {                       // a sample: the ids in a file ([id, ...])
      const ids = new Set(JSON.parse(fs.readFileSync(path.resolve(opt("--ids")), "utf8")));
      profiles = profiles.filter((p) => ids.has(p.id));
    }
    report.profiles = profiles.length;

    if (!flag("--skip-form")) {
      console.log(`(a) form: ${profiles.length} profiles ...`);
      await partForm(page, profiles, report);
    }
    if (!flag("--skip-check")) {
      const checkProfiles = profiles;
      console.log(`(b) check: ${checkProfiles.length} profiles ...`);
      await partCheck(page, checkProfiles, expected, report);
      await feedbackRoundTrip(page, server, report);
      report.worker_posts = {
        usage: (server.posts.length ? server.posts : captured).filter((p) => p.path === "/api/usage").length,
        placement: (server.posts.length ? server.posts : captured).filter((p) => p.path === "/api/placement").length,
        feedback: (server.posts.length ? server.posts : captured).filter((p) => p.path === "/api/feedback").length,
      };
      const u = server.posts.find((p) => p.path === "/api/usage")?.body;
      report.usage_example = u;
      report.placement_example = server.posts.find((p) => p.path === "/api/placement")?.body?.results?.slice(0, 2);
    }
    report.page_errors = errors;
    report.external_requests = external;
  } finally {
    await browser.close();
    server.close();
  }
  // round 44: never the candidate's own path (an --out without "candidate_" in its name overwrote the candidate)
  const rp = path.basename(OUT).includes("candidate_") ? OUT.replace(/candidate_/, "report_")
    : OUT.replace(/(\.jsonl?)?$/, ".report.json");
  fs.writeFileSync(rp, JSON.stringify(report, null, 1));

  console.log(`\nmode ${MODE}  (${report.url})`);
  report.loads.forEach((l, i) => console.log(`first load ${i + 1}: ${l.wall_s.toFixed(2)} s wall (pyodide `
    + `${l.pyodide_s.toFixed(2)} s, bundle unpack ${l.bundle_s.toFixed(2)} s, import ${l.import_s.toFixed(2)} s, `
    + `spec ${l.spec_s.toFixed(2)} s, form ${l.form_s.toFixed(2)} s); ${l.requests} requests to the site`));
  if (report.form) {
    const f = report.form;
    console.log(`(a) form: ${f.profiles} profiles; pd equal ${f.pd_equal}; expressible (pd and topics) ${f.expressible}`);
    console.log("    checked topics: " + JSON.stringify(f.checked));
    console.log("    not expressible, by group: " + JSON.stringify(f.not_expressible_by_group));
    console.log("    fill + submit: " + fmt(f.fill_and_submit_s));
    for (const d of f.differences.slice(0, 40)) console.log(`    ${String(d.count).padStart(5)}  ${d.key}: ${d.kind} -- ${d.why}`);
  }
  if (report.check) {
    const c = report.check;
    console.log(`(b) check: ${c.checked}/${c.profiles} profiles, ${c.cards} cards; `
      + (c.compared_with_fixtures ? `differences vs fixtures: ${c.differences}` : `(no expected values here: `
        + `compare the candidate with the golden: web/tests/candidate_to_golden.py)`));
    for (const d of c.first_differences) console.log("    " + JSON.stringify(d).slice(0, 300));
    console.log("    engine: " + fmt(c.engine_s));
    console.log("    render: " + fmt(c.render_s));
    console.log(`    placement panel shown: ${c.placement_panel_shown}; Worker posts ${JSON.stringify(report.worker_posts)}`);
    console.log("    feedback: " + JSON.stringify(report.feedback));
    console.log("    candidate: " + c.candidate);
  }
  console.log(`requests outside localhost (aborted): ${external.length}${external.length ? " " + JSON.stringify(external.slice(0, 5)) : ""}`);
  console.log(`page errors: ${report.page_errors?.length ?? 0}${report.page_errors?.length ? " " + JSON.stringify(report.page_errors.slice(0, 5)) : ""}`);
  console.log("report: " + rp);
  const failed = (report.check && report.check.compared_with_fixtures && report.check.differences)
    || (report.feedback && report.feedback.ok === false) || (report.page_errors || []).length || external.length;
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
