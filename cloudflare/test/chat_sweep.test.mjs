// Round 47 (Liam and Jonathan, 2026-11): node --test cloudflare/test/chat_sweep.test.mjs
// A cross-carrier question names every program in scope, each with the checker's label (chat_sweep.js). Zero API: the
// model is a fake. The questions are verification/chat/sweep_questions.csv (the live run uses the same file).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { loadWorker, makeDb } from "../scripts/harness.mjs";
import { parseCsv } from "../scripts/lib.mjs";
import { COOKIE, signSession } from "../src/session.js";

const { worker } = await loadWorker();
const { default: CHAT } = await import("../build/chat_index.js");
const { plan, systemPrompt, userMessage } = await import("../src/chat.js");
const { detectSweep, finishSweep, sweepLines, SWEEP_GROUPS } = await import("../src/chat_sweep.js");
const route = await import("../src/chat_route.js");

const QUESTIONS = parseCsv(readFileSync(new URL("../../verification/chat/sweep_questions.csv", import.meta.url), "utf8"));
const OUT = CHAT.sweep.sweeps;
const LABELS = new Set(SWEEP_GROUPS);
const SECRETS = { APP_PASSWORD: "agents-pass-2026", ADMIN_PASSWORD: "admin-pass-2026!",
  SESSION_SECRET: "s".repeat(24) + "-0123456789abcdef" };

test("each test question is a sweep of the right topic and scope, naming EVERY program in that scope", () => {
  assert.ok(QUESTIONS.length >= 18);
  for (const q of QUESTIONS) {
    const r = plan(CHAT, q.question);
    assert.ok(r.sweep, `${q.id} is not a sweep: ${q.question}`);
    assert.equal(`${r.sweep.key}|${r.sweep.scope}`, `${q.key}|${q.scope}`, q.id);
    const want = Object.keys(OUT[q.key][q.scope]).sort();
    assert.deepEqual(r.sweep.programs.map((p) => p.program).sort(), want, `${q.id}: a program is missing`);
    for (const p of r.sweep.programs) {
      assert.ok(LABELS.has(p.label), `${q.id} ${p.name}: label ${p.label}`);
      assert.equal(p.label, OUT[q.key][q.scope][p.program].label, `${q.id} ${p.name}`);
      assert.ok(Number.isInteger(p.p), `${q.id} ${p.program}: not a chat program`);
    }
    // grouped: Eligible, Confirm, Refer, Not eligible, Coverage limited, Guide silent, Closed
    const ranks = r.sweep.programs.map((p) => SWEEP_GROUPS.indexOf(p.label));
    assert.deepEqual(ranks, [...ranks].sort((a, b) => a - b), q.id);
  }
});

test("Liam's question: every HO3 program, the Hartford a Refer on HAR-058 (two phrasings)", () => {
  const ho3 = CHAT.sweep.scopes.HO3.programs.map((p) => p.program).sort();
  for (const q of ["Which carriers will take an above ground pool with no fence",
    "Which carriers will write a home with an above-ground pool that isn't fenced?"]) {
    const sw = plan(CHAT, q).sweep;
    assert.deepEqual(sw.programs.map((p) => p.program).sort(), ho3, q);
    const h = sw.programs.find((p) => p.program === "The_Hartford_HO3_-_07.09.2026");
    assert.equal(h.label, "Refer", q);
    assert.equal(h.rows[0], "HAR-058", q);
  }
});

test("scope: a rental word means DP3, a condo word HO6, otherwise HO3; the other scopes are offered", () => {
  for (const [q, scope] of [["Which carriers decline galvanized plumbing?", "HO3"],
    ["Which landlord carriers decline galvanized plumbing?", "DP3"], ["galvanized plumbing on a rental: who declines it?", "DP3"],
    ["Which DP3 carriers decline galvanized plumbing?", "DP3"], ["Which condo carriers decline galvanized plumbing?", "HO6"]]) {
    const sw = plan(CHAT, q).sweep;
    assert.equal(sw.scope, scope, q);
    assert.ok(sw.others.length >= 1, q);
  }
});

test("values read from the question: a roof's age, a number of losses, a breed by name", () => {
  for (const [q, key] of [["Which carriers take a roof that is 20+ years old?", "roof_age/20"],
    ["Which carriers take a roof older than 20 years?", "roof_age/21"], ["who takes a 25 year old roof", "roof_age/25"],
    ["Which carriers take a home with 2 losses in 3 years?", "losses/2"], ["which carriers allow two claims", "losses/2"],
    ["Which carriers take a home with a pit bull?", "dogs/Pit Bull (American Pit Bull Terrier)"],
    ["Which carriers take a pitbull?", "dogs/Pit Bull (American Pit Bull Terrier)"],
    ["Which carriers take a Staffordshire bull terrier?", "dogs/Staffordshire Bull Terrier"],
    ["Which carriers take a German Shepherd?", "dogs/German Shepherd"], ["Which carriers take dogs?", "dogs/any"]]) {
    assert.equal(plan(CHAT, q).sweep.key, key, q);
  }
});

test("a question that names a carrier, or has no sweep topic, keeps the search path", () => {
  for (const q of ["Does the Hartford take an above ground pool with no fence?", "Does Mercury decline galvanized plumbing?",
    "What is the maximum Coverage A any carrier writes?", "Which carriers have a hail deductible?"]) {
    assert.equal(plan(CHAT, q).sweep, undefined, q);
  }
  assert.equal(detectSweep(CHAT, "What is the maximum Coverage A any carrier writes?"), null);
});

test("the model reads every program with its label; its lines are P<number>; one it skips is filled from the rows", () => {
  const r = plan(CHAT, "Which carriers will take an above ground pool with no fence");
  const msg = userMessage(CHAT, r, "Which carriers will take an above ground pool with no fence", []);
  for (const p of r.sweep.programs) assert.ok(msg.includes(`P${p.k} ${p.name} | label: ${p.label}`), p.name);
  assert.match(systemPrompt(CHAT), /SWEEP list/);
  // two ways a model writes its lines
  assert.deepEqual(sweepLines("P1: no fence rule [S1]\nP2 - declines it [S3]\n"), { 1: "no fence rule [S1]", 2: "declines it [S3]" });
  assert.deepEqual(sweepLines("**P1**: no fence rule [S1]\n  P12) refers it [S9]"), { 1: "no fence rule [S1]", 12: "refers it [S9]" });
  const half = r.sweep.programs.slice(0, 5).map((p) => `P${p.k}: as the guide says [S${p.srcs[0] || 1}]`).join("\n");
  const { lines, filled } = finishSweep(CHAT, r.sweep, half);
  assert.equal(Object.keys(lines).length, r.sweep.programs.length);
  assert.equal(filled.length, r.sweep.programs.length - 5);
  for (const k of filled) assert.ok(lines[k].trim().length > 5, `P${k} is empty`);
});

function fakeModel(text) {
  route.setChatClientFactory(async () => ({ messages: { create: async (params) => {
    fakeModel.params = params;
    return { async *[Symbol.asyncIterator]() {
      yield { type: "message_start", message: { usage: { input_tokens: 9000, output_tokens: 1 } } };
      for (const p of text.match(/.{1,40}/gs) || []) yield { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: p } };
      yield { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { output_tokens: 900 } };
    } };
  } } }));
}

test("POST /api/chat on a sweep: the table first, then every program's line, every source", async () => {
  const q = "Which carriers will take an above ground pool with no fence";
  const sw = plan(CHAT, q).sweep;
  fakeModel(sw.programs.slice(0, 3).map((p) => `P${p.k}: what the guide says [S${p.srcs[0] || 1}]`).join("\n"));
  const db = makeDb();
  const cookie = await signSession({ role: "agent", name: "Jo", exp: Math.floor(Date.now() / 1000) + 3600 }, SECRETS.SESSION_SECRET);
  const env = { DB: db, AUTH_MODE: "password", ...SECRETS, ANTHROPIC_API_KEY: "sk-ant-api03-FAKE", CHAT_DAILY_CAP_USD: "3",
    CHAT_RATE_PER_HOUR: "30", ASSETS: { fetch: async () => new Response("asset") } };
  const pending = [];
  const r = await worker.fetch(new Request("https://x.workers.dev/api/chat", { method: "POST",
    headers: { "content-type": "application/json", cookie: `${COOKIE}=${cookie}` }, body: JSON.stringify({ question: q }) }),
  env, { waitUntil: (p) => pending.push(p) });
  const events = (await r.text()).trim().split("\n").map((l) => JSON.parse(l));
  await Promise.all(pending);
  const start = events[0], done = events.find((e) => e.t === "done");
  assert.equal(start.mode, "sweep");
  assert.equal(start.sweep.programs.length, sw.programs.length);
  assert.match(start.sweep.scope_line, /^28 HO3 \(owner-occupied home\) programs, for an above-ground pool with no fence\./);
  assert.equal(Object.keys(done.sweep_lines).length, sw.programs.length);
  assert.equal(done.sweep_filled.length, sw.programs.length - 3);
  assert.equal(done.citations.length, sw.programs.reduce((n, p) => n + p.srcs.length, 0));
  assert.ok(done.citations.every((c) => String(c.text || "").trim()), "an empty source");
  assert.equal(fakeModel.params.max_tokens, route.SWEEP_MAX_TOKENS);
});

test("the sweep's lookup stays far under the Free plan's 10 ms (median of the test questions, Node)", () => {
  const ms = QUESTIONS.map((q) => { const t = process.hrtime.bigint(); plan(CHAT, q.question); return Number(process.hrtime.bigint() - t) / 1e6; })
    .sort((a, b) => a - b);
  assert.ok(ms[Math.floor(ms.length / 2)] < 3, `median ${ms[Math.floor(ms.length / 2)]} ms`);
});
