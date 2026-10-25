// The password gate's CPU per request (round 44 step 1), against the Workers Free plan's 10 ms: the Worker now runs
// for every static file too. Same method as bench_cpu.mjs: blocks of N requests timed with process.cpuUsage()
// (Windows' clock ticks every ~15.6 ms), ASSETS a stub, D1 the node:sqlite stand-in.
//   usage (cwd = the repo root): node cloudflare/scripts/bench_gate.mjs [--n 2000] [--blocks 3]
import worker from "../src/worker.js";
import { COOKIE, signSession } from "../src/session.js";
import { DEFAULT_CSV_DIR, makeDb } from "./harness.mjs";

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i < 0 ? d : args[i + 1]; };
const N = parseInt(opt("--n", "2000"), 10), BLOCKS = parseInt(opt("--blocks", "3"), 10);
const SECRETS = { APP_PASSWORD: "bench-agent-pass-1", ADMIN_PASSWORD: "bench-admin-pass-2", SESSION_SECRET: "b".repeat(48) };
const db = makeDb(DEFAULT_CSV_DIR, []);
const env = { DB: db, AUTH_MODE: "password", ...SECRETS,
  ASSETS: { fetch: async () => new Response("x".repeat(1024), { status: 200, headers: { etag: '"1"' } }) } };
const BASE = "https://cfig-eligibility.example.workers.dev";
const now = Math.floor(Date.now() / 1000);
const cookie = await signSession({ role: "agent", name: "Bench", iat: now, exp: now + 86400 }, SECRETS.SESSION_SECRET);
const mk = (path, init = {}) => () => new Request(BASE + path, init);
let ip = 0;
const form = (password) => () => new Request(BASE + "/login", { method: "POST", body: `password=${password}&next=/`,
  headers: { "content-type": "application/x-www-form-urlencoded", "cf-connecting-ip": `10.0.${(ip >> 8) & 255}.${ip++ & 255}` } });

const ROUTES = [
  ["a static file with a session (cookie checked, then ASSETS)", mk("/pyodide/pyodide.asm.wasm", { headers: { cookie: `${COOKIE}=${cookie}` } })],
  ["the page with a session", mk("/", { headers: { cookie: `${COOKIE}=${cookie}`, accept: "text/html" } })],
  ["/api/whoami with a session", mk("/api/whoami", { headers: { cookie: `${COOKIE}=${cookie}` } })],
  ["no session: refused (401 / redirect)", mk("/engine.tar.gz")],
  ["GET /login", mk("/login", { headers: { accept: "text/html" } })],
  ["POST /login, right password (+ D1 clear)", form(SECRETS.APP_PASSWORD)],
  ["POST /login, wrong password (+ D1 count)", form("wrong-one")],
];

console.log(`node ${process.version}, ${N} requests a block, ${BLOCKS} blocks`);
for (const [label, make] of ROUTES) {
  const reqs = () => Array.from({ length: N }, make);
  for (let i = 0; i < 50; i++) await worker.fetch(make(), env, {});          // warm (the HMAC key is cached)
  const blocks = [];
  for (let b = 0; b < BLOCKS; b++) {
    const rs = reqs();
    const t = process.cpuUsage();
    for (const r of rs) { const res = await worker.fetch(r, env, {}); await res.arrayBuffer(); }
    const d = process.cpuUsage(t);
    blocks.push(((d.user + d.system) / 1000 / N).toFixed(3));
  }
  console.log(`${label} | ${blocks.join(", ")} ms/request`);
}
