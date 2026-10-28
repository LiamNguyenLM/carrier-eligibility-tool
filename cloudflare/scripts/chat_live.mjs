// Ask the Guides, live (round 45): questions through the Worker's own POST /api/chat (password gate, cost guard, the
// real Anthropic call), on Node with node:sqlite for D1. PAID: run it through verification/chat/run_live.py, which
// loads the key into this process's environment only (env_setup.load_env); this script never prints it.
//
//   python verification/chat/run_live.py [--ids Q01,Q07] [--cap 2.00] [--out verification/chat/out/run.jsonl]
//
// Writes one JSON line per question: id, question, answer, citations, unverified quotes, stop reason, tokens, cost,
// time to the first words and to the end (wall clock, this laptop to the API), and the Worker's CPU for the request
// (process.cpuUsage() around the whole request, waiting on the API excluded since it is I/O).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { loadWorker, makeDb } from "./harness.mjs";
import { parseCsv } from "./lib.mjs";
import { COOKIE, signSession } from "../src/session.js";

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i < 0 ? d : args[i + 1]; };
const CAP = Number(opt("--cap", "2.00"));
const OUT = resolve(opt("--out", "verification/chat/out/run.jsonl"));
const ids = opt("--ids", "") ? new Set(opt("--ids", "").split(",")) : null;
const questions = parseCsv(readFileSync(resolve(opt("--questions", "verification/chat/questions.csv")), "utf8"))
  .filter((q) => !ids || ids.has(q.id));
if (!process.env.ANTHROPIC_API_KEY) { console.error("no API key in this process (run it through run_live.py)"); process.exit(2); }

const { worker } = await loadWorker();
const SECRETS = { APP_PASSWORD: "live-agents-pass", ADMIN_PASSWORD: "live-admin-pass!", SESSION_SECRET: "l".repeat(32) };
const db = makeDb();
const env = { DB: db, AUTH_MODE: "password", ...SECRETS, ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
  CHAT_MODEL: opt("--model", "claude-haiku-5-5"), CHAT_DAILY_CAP_USD: String(CAP), CHAT_RATE_PER_HOUR: "1000",
  ASSETS: { fetch: async () => new Response("asset") } };
const cookie = await signSession({ role: "agent", name: "Live Test", exp: Math.floor(Date.now() / 1000) + 7200 },
  SECRETS.SESSION_SECRET);

mkdirSync(dirname(OUT), { recursive: true });
const lines = [];
let spent = 0;
for (const q of questions) {
  if (spent >= CAP) { console.log(`cap $${CAP} reached: stopping before ${q.id}`); break; }
  const history = q.history ? JSON.parse(q.history) : [];
  const t0 = performance.now();
  const c0 = process.cpuUsage();
  const pending = [];
  const res = await worker.fetch(new Request("https://cfig-eligibility.example.workers.dev/api/chat", {
    method: "POST", headers: { "content-type": "application/json", cookie: `${COOKIE}=${cookie}` },
    body: JSON.stringify({ question: q.question, history }) }), env, { waitUntil: (p) => pending.push(p) });
  let answer = "", done = null, error = null, firstWall = 0;
  if (res.status !== 200) {
    error = `${res.status} ${(await res.json()).error}`;
  } else {
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const ev = JSON.parse(buf.slice(0, i));
        buf = buf.slice(i + 1);
        if (ev.t === "text") { if (!firstWall) firstWall = performance.now() - t0; answer += ev.d; }
        if (ev.t === "done") done = ev;
        if (ev.t === "error") error = ev.error;
      }
    }
  }
  await Promise.all(pending);
  const cpu = process.cpuUsage(c0);
  const row = db.sqlite.prepare("SELECT * FROM chat_log ORDER BY id DESC LIMIT 1").get() || {};
  spent += Number(row.cost_usd || 0);
  const out = { id: q.id, question: q.question, answer, error, citations: done ? done.citations : [],
    unverified: done ? done.unverified : [], stop: done ? done.stop : null, model: env.CHAT_MODEL,
    input_tokens: row.input_tokens, output_tokens: row.output_tokens, cache_read: row.cache_read_tokens,
    cost_usd: row.cost_usd, first_ms: Math.round(firstWall), total_ms: Math.round(performance.now() - t0),
    worker_first_ms: done ? done.first_ms : null, node_cpu_ms: +((cpu.user + cpu.system) / 1000).toFixed(1),
    programs: row.programs };
  lines.push(JSON.stringify(out));
  console.log(`${q.id}: ${error ? "ERROR " + error : (done ? done.stop : "no done")} first ${out.first_ms} ms, total `
    + `${out.total_ms} ms, ${out.input_tokens}+${out.output_tokens} tokens, $${Number(out.cost_usd || 0).toFixed(5)}, `
    + `${out.citations.length} citations${out.unverified.length ? `, ${out.unverified.length} UNVERIFIED quote(s)` : ""}`);
  writeFileSync(OUT, lines.join("\n") + "\n");
}
console.log(`${lines.length} questions, $${spent.toFixed(4)} -> ${OUT}`);
