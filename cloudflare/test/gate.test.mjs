// The shared-password gate (round 44 step 1, Liam 2026-10-25): node --test cloudflare/test/gate.test.mjs
// Zero network. D1 is node:sqlite (with the migrations, login_failures included); ASSETS is a stub that counts calls,
// so a test can prove a refused request never reached a static file.
import assert from "node:assert/strict";
import { before, test } from "node:test";
import { COOKIE, MAX_FAILURES, SESSION_DAYS, signSession } from "../src/session.js";
import { loadWorker, makeDb } from "../scripts/harness.mjs";

const { worker } = await loadWorker();

const SECRETS = { APP_PASSWORD: "agents-pass-2026", ADMIN_PASSWORD: "admin-pass-2026!",
  SESSION_SECRET: "s".repeat(24) + "-0123456789abcdef" };
const BASE = "https://cfig-eligibility.example.workers.dev";
let db;
let assetCalls = 0;
const envOf = (vars = {}) => ({ DB: db, AUTH_MODE: "password", ...SECRETS,
  ASSETS: { fetch: async () => { assetCalls++; return new Response("asset", { status: 200, headers: { etag: '"1"' } }); } },
  ...vars });
const call = (r, e = envOf()) => worker.fetch(r, e, {});

function get(path, { cookie, accept = "*/*", ip = "203.0.113.7", method = "GET", body, type } = {}) {
  const headers = { accept, "cf-connecting-ip": ip };
  if (cookie) headers.cookie = `${COOKIE}=${cookie}`;
  if (type) headers["content-type"] = type;
  return new Request(BASE + path, { method, headers, body });
}
const form = (fields) => new URLSearchParams(fields).toString();
const postLogin = (fields, ip) => get("/login", { method: "POST", body: form(fields), ip,
  type: "application/x-www-form-urlencoded" });

async function loginAs(password, name = "") {
  const r = await call(postLogin({ password, name, next: "/" }));
  assert.equal(r.status, 303);
  const m = /cfig_session=([^;]+)/.exec(r.headers.get("set-cookie") || "");
  return m[1];
}

before(() => { db = makeDb(); });

// every kind of path the site serves: the page, its scripts, the engine bundle, Pyodide, the rules data, the API
const PATHS = [["GET", "/"], ["GET", "/index.html"], ["GET", "/src/app.js"], ["GET", "/engine.tar.gz"],
  ["GET", "/pyodide/pyodide.asm.wasm"], ["GET", "/build.json"], ["GET", "/rules_data/carrier_rules_pilot_v5.csv"],
  ["GET", "/api/whoami"], ["POST", "/api/usage"], ["POST", "/api/feedback"], ["POST", "/api/placement"],
  ["GET", "/api/admin/feedback.csv"], ["GET", "/api/admin/weekly"], ["GET", "/nope"],
  ["POST", "/api/chat"], ["GET", "/api/admin/chat.csv"]];                    // round 45: Ask the Guides

async function refused(r, label) {
  assert.ok([302, 401, 503].includes(r.status), `${label}: ${r.status}`);
  const text = await r.text();
  assert.ok(!text.includes("asset"), `${label} leaked content`);
  if (r.status === 302) assert.match(r.headers.get("location"), /^\/login\?next=/, label);
}

test("no path answers without a session: a page visit goes to /login, anything else gets 401", async () => {
  const before = assetCalls;
  for (const [m, p] of PATHS) {
    for (const accept of ["text/html,application/xhtml+xml", "*/*"]) {
      const r = await call(get(p, { method: m, accept, type: m === "POST" ? "application/json" : undefined,
        body: m === "POST" ? "{}" : undefined }));
      await refused(r, `${m} ${p} (${accept})`);
      if (p.startsWith("/api/") || accept === "*/*" && p !== "/" && !p.endsWith(".html")) assert.equal(r.status, 401, p);
    }
  }
  assert.equal(assetCalls, before, "a refused request reached a static file");
});

test("the login page: a wrong password is a generic error, the right one an HttpOnly Secure SameSite=Lax 7-day cookie", async () => {
  const page = await call(get("/login", { accept: "text/html" }));
  assert.equal(page.status, 200);
  assert.match(await page.text(), /type="password"/);
  const wrong = await call(postLogin({ password: "nope", next: "/" }, "198.51.100.1"));
  assert.equal(wrong.status, 401);
  assert.match(await wrong.text(), /That password isn&#39;t right|That password isn't right/);
  assert.equal(wrong.headers.get("set-cookie"), null);
  const ok = await call(postLogin({ password: SECRETS.APP_PASSWORD, name: "Dana", next: "/" }, "198.51.100.1"));
  assert.equal(ok.status, 303);
  const c = ok.headers.get("set-cookie");
  for (const part of ["HttpOnly", "Secure", "SameSite=Lax", "Path=/", `Max-Age=${SESSION_DAYS * 86400}`]) {
    assert.ok(c.includes(part), part);
  }
});

test("an agent session gets the site and the API, not the admin routes; the name fills whoami", async () => {
  const s = await loginAs(SECRETS.APP_PASSWORD, "Dana Agent");
  const page = await call(get("/", { cookie: s, accept: "text/html" }));
  assert.equal(page.status, 200);
  assert.equal(await page.text(), "asset");
  assert.equal(page.headers.get("cache-control"), "private, no-cache");
  const who = await (await call(get("/api/whoami", { cookie: s }))).json();
  assert.deepEqual(who, { email: "", admin: false, name: "Dana Agent", mode: "password", logout: "/logout" });
  for (const p of ["/api/admin/feedback.csv", "/api/admin/weekly"]) {
    assert.equal((await call(get(p, { cookie: s }))).status, 403, p);
  }
});

test("the admin password gives an admin session: the admin routes answer", async () => {
  const s = await loginAs(SECRETS.ADMIN_PASSWORD);
  assert.equal((await call(get("/api/admin/weekly", { cookie: s }))).status, 200);
  const csv = await call(get("/api/admin/feedback.csv", { cookie: s }));
  assert.equal(csv.status, 200);
  assert.match(await csv.text(), /^ts,/);
});

test("a tampered, re-signed, expired or malformed cookie is refused", async () => {
  const good = await loginAs(SECRETS.APP_PASSWORD);
  const [v, body, sig] = good.split(".");
  const now = Math.floor(Date.now() / 1000);
  const asAdmin = Buffer.from(JSON.stringify({ role: "admin", name: "", iat: now, exp: now + 3600 })).toString("base64url");
  const cases = {
    "payload changed to admin, old signature": `${v}.${asAdmin}.${sig}`,
    "signature changed": `${v}.${body}.${sig.slice(0, -2)}${sig.endsWith("AA") ? "BB" : "AA"}`,
    "signed with another secret": await signSession({ role: "admin", name: "", iat: now, exp: now + 3600 }, "x".repeat(40)),
    "expired": await signSession({ role: "agent", name: "", iat: now - 9 * 86400, exp: now - 1 }, SECRETS.SESSION_SECRET),
    "unknown role": await signSession({ role: "root", name: "", iat: now, exp: now + 3600 }, SECRETS.SESSION_SECRET),
    "garbage": "not-a-session",
    "empty": "",
  };
  for (const [label, cookie] of Object.entries(cases)) {
    await refused(await call(get("/engine.tar.gz", { cookie })), label);
    await refused(await call(get("/api/admin/weekly", { cookie })), label + " (admin)");
  }
});

test(`${MAX_FAILURES} wrong passwords lock that address out, even for the right one; another address is not`, async () => {
  const ip = "192.0.2.50";
  for (let i = 0; i < MAX_FAILURES; i++) assert.equal((await call(postLogin({ password: "guess" + i }, ip))).status, 401);
  const locked = await call(postLogin({ password: SECRETS.APP_PASSWORD }, ip));
  assert.equal(locked.status, 429);
  assert.match(await locked.text(), /Too many wrong passwords/);
  assert.equal(locked.headers.get("set-cookie"), null);
  assert.equal((await call(postLogin({ password: SECRETS.APP_PASSWORD }, "192.0.2.51"))).status, 303);
  // the lockout over: the right password works again and clears the counter
  db.sqlite.prepare("UPDATE login_failures SET locked_until = 0, window_start = 0 WHERE ip = ?").run(ip);
  assert.equal((await call(postLogin({ password: SECRETS.APP_PASSWORD }, ip))).status, 303);
  assert.equal(db.sqlite.prepare("SELECT count(*) AS n FROM login_failures WHERE ip = ?").get(ip).n, 0);
});

// Round 44b (Liam, 2026-10-25): "if the login-lockout counter ... can't write, login and checks still work (log the
// error)". Three ways D1 can fail the counter: its writes refused, every call failing, and the reads failing too.
test("the lockout counter failing in D1 never stops a login or a check; the error is logged", async () => {
  const refused = () => Promise.reject(new Error("D1_ERROR: Exceeded maximum rows written per day"));
  const writesRefused = { prepare: (sql) => {
    const wrap = (st) => ({ bind: (...p) => wrap(st.bind(...p)), first: (c) => st.first(c), all: () => st.all(), run: refused });
    return wrap(db.prepare(sql));
  }, batch: refused };
  const unreachable = { prepare: () => { throw new Error("D1_ERROR: Network connection lost"); }, batch: refused };
  const readsFail = { prepare: () => ({ bind() { return this; }, first: refused, all: refused, run: refused }), batch: refused };
  for (const [label, bad] of Object.entries({ "writes refused": writesRefused, "D1 unreachable": unreachable,
    "reads and writes fail": readsFail })) {
    const e = envOf({ DB: bad });
    const logged = [], orig = console.error;
    console.error = (...a) => logged.push(a.map(String).join(" "));
    try {
      const wrong = await call(postLogin({ password: "not-it" }, "198.51.100.9"), e);
      assert.equal(wrong.status, 401, label);
      assert.match(await wrong.text(), /That password isn&#39;t right\.|That password isn't right\./, label);
      const ok = await call(postLogin({ password: SECRETS.APP_PASSWORD, name: "Jo", next: "/" }, "198.51.100.9"), e);
      assert.equal(ok.status, 303, label);
      const cookie = /cfig_session=([^;]+)/.exec(ok.headers.get("set-cookie") || "")[1];
      assert.equal((await call(get("/", { cookie }), e)).status, 200, label);
      const usage = await call(get("/api/usage", { cookie, method: "POST", type: "application/json",
        body: JSON.stringify({ carriers: 3 }) }), e);
      assert.equal(usage.status, 202, label);
      const fb = await call(get("/api/feedback", { cookie, method: "POST", type: "application/json",
        body: JSON.stringify({ carrier: "TWICO_HO3", comment: "x" }) }), e);
      assert.equal(fb.status, 503, label);
      assert.equal((await fb.json()).error, "Couldn’t save — try again later.", label);
    } finally {
      console.error = orig;
    }
    assert.ok(logged.some((l) => l.startsWith("login_failures write failed")), `${label}: ${logged}`);
    if (label !== "writes refused") assert.ok(logged.some((l) => l.startsWith("login_failures read failed")), label);
  }
});

test("a missing or weak secret fails closed: every path refuses, the login page says the tool isn't set up", async () => {
  const s = await loginAs(SECRETS.APP_PASSWORD);
  const broken = {
    "no APP_PASSWORD": { APP_PASSWORD: "" }, "no ADMIN_PASSWORD": { ADMIN_PASSWORD: undefined },
    "no SESSION_SECRET": { SESSION_SECRET: "" }, "short SESSION_SECRET": { SESSION_SECRET: "short" },
    "same passwords": { ADMIN_PASSWORD: SECRETS.APP_PASSWORD }, "short password": { APP_PASSWORD: "abc" },
  };
  for (const [label, vars] of Object.entries(broken)) {
    const e = envOf(vars);
    const page = await call(get("/login", { accept: "text/html" }), e);
    assert.equal(page.status, 503, label);
    assert.match(await page.text(), /isn't set up yet/, label);
    const before = assetCalls;
    for (const [m, p] of PATHS) {
      const r = await call(get(p, { method: m, cookie: s }), e);
      assert.equal(r.status, 503, `${label}: ${m} ${p}`);
    }
    const login = await call(postLogin({ password: SECRETS.APP_PASSWORD }), e);
    assert.equal(login.status, 503, label);
    assert.equal(login.headers.get("set-cookie"), null, label);
    assert.equal(assetCalls, before, label);
  }
});

test("an unknown AUTH_MODE fails closed for every path", async () => {
  for (const mode of ["passwd", "none", "off"]) {
    for (const [m, p] of PATHS) {
      assert.equal((await call(get(p, { method: m }), envOf({ AUTH_MODE: mode }))).status, 503, `${mode} ${p}`);
    }
  }
});

test("logout ends the session; next never leaves the site", async () => {
  const out = await call(get("/logout"));
  assert.equal(out.status, 303);
  assert.match(out.headers.get("set-cookie"), /cfig_session=; Path=\/; Max-Age=0/);
  for (const next of ["//evil.example/x", "https://evil.example/", "/\\evil.example", "/login", "/a\r\nSet-Cookie: x=1"]) {
    const r = await call(postLogin({ password: SECRETS.APP_PASSWORD, next }, "198.51.100.9"));
    assert.equal(r.headers.get("location"), "/", next);
  }
  const r = await call(postLogin({ password: SECRETS.APP_PASSWORD, next: "/?zip=77002" }, "198.51.100.9"));
  assert.equal(r.headers.get("location"), "/?zip=77002");
});

test("access mode is unchanged: the static site is served as it is, the API needs Access's token", async () => {
  const e = envOf({ AUTH_MODE: "access", ACCESS_TEAM_DOMAIN: "team.cloudflareaccess.com", ACCESS_AUD: "a".repeat(64) });
  assert.equal(await (await call(get("/engine.tar.gz"), e)).text(), "asset");
  assert.equal((await call(get("/api/whoami"), e)).status, 401);
  assert.equal((await call(get("/login"), e)).status, 200);     // no login route in access mode: a static path
  assert.equal(await (await call(get("/login"), e)).text(), "asset");
});
