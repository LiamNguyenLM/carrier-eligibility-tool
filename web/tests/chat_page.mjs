#!/usr/bin/env node
// Round 45 (Liam, 2026-10-28): the "Ask the Guides" tab in a real browser (Playwright, the installed Microsoft Edge).
// Zero API: the page is web/dist on tools/serve.mjs, and POST /api/chat is answered in the browser with a recorded
// answer from the live test (verification/chat/run_live.py's JSONL), streamed as the Worker streams it.
//
//   node web/tests/chat_page.mjs --answers <run.jsonl> --profiles <parity inputs json> [--id Q01] [--dist web/dist] [--headed]
// (--profiles: the list web/tests/parity.mjs takes; its first profile is checked after the chat)
//
// Checks: the tab switches; the answer renders as it streams, with [S#] as links and a Sources list naming carrier,
// guide date and page; "This answer looks wrong" posts kind "chat"; a 429 (the spend cap) and a dropped connection
// show their messages; and the eligibility check still loads and runs after the chat (the checker is untouched).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { startServer } from "../tools/serve.mjs";

const WEB = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const argv = process.argv.slice(2);
const opt = (k, d) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : d);
const DIST = path.resolve(WEB, opt("--dist", "dist"));
const answers = fs.readFileSync(path.resolve(opt("--answers")), "utf8").trim().split("\n").map((l) => JSON.parse(l));
const rec = answers.find((a) => a.id === opt("--id", "Q01"));
if (!opt("--profiles")) { console.error("--profiles <file> is needed"); process.exit(2); }

const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); };

function ndjson(r) {
  const pieces = r.answer.match(/[\s\S]{1,40}/g) || [];
  return [{ t: "start", carriers: [], mode: "named" }, ...pieces.map((d) => ({ t: "text", d })),
    { t: "done", citations: r.citations, unverified: r.unverified, stop: r.stop, cost_usd: r.cost_usd,
      first_ms: r.first_ms, total_ms: r.total_ms }].map((e) => JSON.stringify(e)).join("\n") + "\n";
}

const server = await startServer({ dir: DIST, mockApi: true });
const BASE = server.url.replace(/\/$/, "");
const browser = await chromium.launch({ channel: "msedge", headless: !argv.includes("--headed") });
const errors = [];
try {
  const ctx = await browser.newContext();
  let mode = "ok";
  const posts = [];
  await ctx.route("**/api/chat", async (route) => {
    posts.push(route.request().postDataJSON());
    if (mode === "cap") {
      return route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ reason: "daily_cap",
        error: "Ask the Guides has reached today's spending limit and is back at midnight UTC (7 pm Central). The eligibility check still works." }) });
    }
    if (mode === "down") return route.abort("connectionfailed");
    return route.fulfill({ status: 200, contentType: "application/x-ndjson", body: ndjson(rec) });
  });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  await page.goto(BASE + "/#chat");
  await page.waitForSelector("#chat:not([hidden]) #chat-q");
  check(await page.locator("#app").isHidden(), "the checker is shown on the chat tab");

  // 1. a question and its streamed answer
  await page.fill("#chat-q", rec.question);
  await page.click("#chat-ask");
  await page.waitForFunction(() => window.__chat.turns().length === 1, null, { timeout: 10000 });
  const turn = page.locator(".chat-turn").first();
  const answerText = await turn.locator(".answer").innerText();
  check(answerText.replace(/\s+/g, " ").includes(rec.answer.replace(/\[S\d+[^\]]*\]/g, "").split("\n")[0].trim().slice(0, 30)),
    "the answer text is not on the page");
  const sups = await turn.locator("sup.cite a").count();
  check(sups >= rec.citations.length, `${sups} citation links for ${rec.citations.length} citations`);
  const cites = await turn.locator(".chat-cites li").allInnerTexts();
  check(cites.length === rec.citations.length, `${cites.length} sources listed, ${rec.citations.length} cited`);
  for (const [i, c] of rec.citations.entries()) {
    const li = cites[i] || "";
    check(li.includes(c.carrier), `source S${c.n}: no carrier`);
    if (c.page) check(li.includes(`page ${c.page}`), `source S${c.n}: no page`);
    if (c.kind === "cfig") check(/CFIG experience/.test(li), `source S${c.n}: CFIG row not labelled`);
  }
  check(posts[0].question === rec.question && Array.isArray(posts[0].history) && !("system" in posts[0]),
    "the page sent more than the question and history");

  // 2. "This answer looks wrong"
  const fb = turn.locator("details.feedback");
  await fb.locator("summary").click();
  await fb.locator("input[type=radio]").first().check();
  await fb.locator("textarea").fill("page looks wrong");
  await fb.locator("button[type=submit]").click();
  await fb.locator(".sent").waitFor({ state: "visible", timeout: 5000 });
  const sent = (await (await fetch(BASE + "/__posts")).json()).filter((p) => p.path === "/api/feedback").at(-1)?.body;
  check(sent && sent.kind === "chat" && sent.question === rec.question && sent.comment === "page looks wrong",
    "chat feedback body: " + JSON.stringify(sent));

  // 3. a follow-up carries the history
  await page.fill("#chat-q", "What about their other rules?");
  await page.click("#chat-ask");
  await page.waitForFunction(() => window.__chat.turns().length === 2);
  check(posts[1].history.length === 1 && posts[1].history[0].q === rec.question, "the follow-up had no history");

  // 4. failures show a clear message
  mode = "cap";
  await page.fill("#chat-q", "One more?");
  await page.click("#chat-ask");
  await page.waitForSelector(".chat-turn:nth-child(3) .chat-note.error");
  check(/spending limit/.test(await page.locator(".chat-turn:nth-child(3) .chat-note").innerText()), "no spend-cap message");
  mode = "down";
  await page.fill("#chat-q", "And another?");
  await page.click("#chat-ask");
  await page.waitForSelector(".chat-turn:nth-child(4) .chat-note.error");
  check(/couldn't be reached/.test(await page.locator(".chat-turn:nth-child(4) .chat-note").innerText()), "no connection message");

  // 5. the checker still works
  await page.click(".tabs button[data-tab=check]");
  await page.waitForFunction(() => window.__eligibility && (window.__eligibility.ready || window.__eligibility.error), null, { timeout: 180000 });
  check(!(await page.evaluate(() => window.__eligibility.error)), "the rules engine did not load");
  // a real profile from the parity inputs (the same list web/tests/parity.mjs runs)
  const prof = JSON.parse(fs.readFileSync(path.resolve(opt("--profiles")), "utf8"))[0];
  const pd = prof.pd;
  const run = await page.evaluate(([p, c]) => window.__eligibility.runCheck(p, c).then(
    (r) => ({ ok: true, r: r && Object.keys(r) }), (e) => ({ ok: false, e: String(e) })), [pd, prof.checked]);
  check(run.ok, "runCheck failed: " + JSON.stringify(run));
  const cards = await page.evaluate(() => (window.__eligibility.readResults() || {}).cards?.length || 0);
  check(cards > 10, `the check rendered ${cards} cards`);
  console.log(`chat tab: ${rec.id}, ${rec.citations.length} citations, ${sups} links; follow-up, feedback, cap and `
    + `connection messages checked; checker after the chat: ${cards} cards`);
} finally {
  await browser.close();
  server.close();
}
check(errors.length === 0, "page errors: " + errors.join("; "));
console.log(problems.length ? "PROBLEMS:\n  " + problems.join("\n  ") : "CHAT PAGE OK");
process.exit(problems.length ? 1 : 0);
