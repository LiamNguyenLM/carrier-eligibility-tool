// Worker CPU per POST /api/chat (round 45), against the Free plan's 10 ms. The model is a fake that streams a real
// answer from run 3 of the live test (so no time is spent waiting on the API, which the 10 ms limit doesn't count
// anyway): everything left is the Worker's own work -- the gate, the cost guard's D1 read (node:sqlite here, an upper
// bound), retrieval, the prompt, relaying the stream, citations, the quote check and the chat_log write.
//
//   node cloudflare/scripts/bench_chat.mjs [--answers ../r45_live/run3.jsonl] [--n 400]
//
// Per request: wall time with the fake model (no awaits on I/O, so wall ~ CPU) -> median and p95; and
// process.cpuUsage() over blocks of requests (Windows' CPU clock ticks every ~15.6 ms, so only blocks are timed).
import { readFileSync } from "node:fs";
import { loadWorker, makeDb } from "./harness.mjs";
import { COOKIE, signSession } from "../src/session.js";

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i < 0 ? d : args[i + 1]; };
const N = parseInt(opt("--n", "400"), 10);
const answers = readFileSync(opt("--answers", "../r45_live/run3.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));

const { worker } = await loadWorker();
const route = await import("../src/chat_route.js");
let current = answers[0];
const sse = (ans) => {
  const ev = (type, data) => `event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`;
  const pieces = ans.answer.match(/\S+\s*\S*\s*\S*\s*\S*\s*\S*\s*/g) || [""];
  return ev("message_start", { message: { id: "msg_bench", type: "message", role: "assistant", model: "claude-haiku-5-5",
    content: [], stop_reason: null, usage: { input_tokens: ans.input_tokens, output_tokens: 1 } } })
    + ev("content_block_start", { index: 0, content_block: { type: "text", text: "" } })
    + pieces.map((p) => ev("content_block_delta", { index: 0, delta: { type: "text_delta", text: p } })).join("")
    + ev("content_block_stop", { index: 0 })
    + ev("message_delta", { delta: { stop_reason: "end_turn" }, usage: { output_tokens: ans.output_tokens } })
    + ev("message_stop", {});
};
if (args.includes("--fetch")) {
  // --fetch: the route's real client (a direct fetch to the Messages API) with fetch() answering the API's SSE events
  // for the answer, so the stream decoding is measured too
  globalThis.fetch = async () => new Response(sse(current), { headers: { "content-type": "text/event-stream" } });
} else route.setChatClientFactory(async () => ({ messages: { create: async () => {
  // the real answer, cut into the ~5-word pieces the API streams, as raw events
  const pieces = current.answer.match(/\S+\s*\S*\s*\S*\s*\S*\s*\S*\s*/g) || [""];
  return {
    async *[Symbol.asyncIterator]() {
      yield { type: "message_start", message: { usage: { input_tokens: current.input_tokens, output_tokens: 1 } } };
      for (const p of pieces) yield { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: p } };
      yield { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { output_tokens: current.output_tokens } };
    },
  };
} } }));

const SECRETS = { APP_PASSWORD: "bench-agents-pass", ADMIN_PASSWORD: "bench-admin-pass!", SESSION_SECRET: "b".repeat(32) };
const db = makeDb();
const env = { DB: db, AUTH_MODE: "password", ...SECRETS, ANTHROPIC_API_KEY: "bench-not-a-key", CHAT_RATE_PER_HOUR: "1000000",
  CHAT_DAILY_CAP_USD: "1000000", ASSETS: { fetch: async () => new Response("x") } };
const cookie = await signSession({ role: "agent", name: "Bench", exp: Math.floor(Date.now() / 1000) + 3600 }, SECRETS.SESSION_SECRET);

async function one(i) {
  current = answers[i % answers.length];
  const req = new Request("https://x.workers.dev/api/chat", { method: "POST",
    headers: { "content-type": "application/json", cookie: `${COOKIE}=${cookie}` }, body: JSON.stringify({ question: current.question }) });
  const pending = [];
  const t0 = performance.now();
  const r = await worker.fetch(req, env, { waitUntil: (p) => pending.push(p) });
  await r.text();
  await Promise.all(pending);
  return performance.now() - t0;
}

for (let i = 0; i < 80; i++) await one(i);                 // warm-up: JIT, statement cache
const wall = [];
const c0 = process.cpuUsage();
const m0 = process.threadCpuUsage ? process.threadCpuUsage() : null;      // the main thread only (no GC/compiler threads)
for (let i = 0; i < N; i++) wall.push(await one(i));
const cpu = process.cpuUsage(c0);
const main = m0 ? process.threadCpuUsage(m0) : null;
wall.sort((a, b) => a - b);
const q = (p) => wall[Math.min(wall.length - 1, Math.floor(p * wall.length))].toFixed(2);
console.log(`node ${process.version}; ${N} requests over the ${answers.length} live answers; chat_log grew to ${db.sqlite.prepare("SELECT count(*) AS n FROM chat_log").get().n} rows`);
console.log(`per request (fake model, wall ~ CPU): median ${q(0.5)} ms, p95 ${q(0.95)} ms, max ${q(0.999)} ms`);
console.log(`process CPU over the block: ${((cpu.user + cpu.system) / 1000 / N).toFixed(2)} ms a request`
  + (main ? `; main thread only: ${((main.user + main.system) / 1000 / N).toFixed(2)} ms a request` : ""));
