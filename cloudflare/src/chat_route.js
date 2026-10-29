// POST /api/chat and GET /api/admin/chat.csv (round 45, Liam 2026-10-28). The answer is chat.js; this is the route:
// the cost guard, the model call, the stream to the browser and the one log row.
//
// Cost guard, before any model call, from ONE D1 read (a batch of two counts over chat_log):
//   - CHAT_RATE_PER_HOUR (default 30) questions per session in the last hour;
//   - CHAT_DAILY_CAP_USD (default 3) of model spend per UTC day, across everyone.
// If chat_log can't be read, chat refuses (it can't know the spend) and the checker is untouched. After the answer,
// ONE write: its chat_log row (time, session, name, question, programs, cited carriers, tokens, cost, model, timings).
//
// The browser gets NDJSON, one event a line:
//   {"t":"start","carriers":[...],"mode":"named"|"follow_up"|"all"}
//   {"t":"text","d":"..."}                       the answer as it is written
//   {"t":"done","citations":[...],"unverified":[...],"stop":"end_turn","cost_usd":0.0012,"first_ms":900,"total_ms":4100}
//   {"t":"error","error":"<a fixed message>"}    the model call failed (never the API's own text, never a key)
import CHAT from "../build/chat_index.js";
import { ChatInputError, citation, citedNumbers, costUsd, parseChatBody, retrieve, systemPrompt, unverifiedQuotes,
  userMessage } from "./chat.js";

// Round 46 (Liam, 2026-10-29): Sonnet 5.5, was Haiku 5.5 (round 45). About 20x Haiku's price per token.
export const DEFAULT_MODEL = "claude-sonnet-5-5";
export const CHAT_MAX_TOKENS = 4000;          // round 46: was 3000; a cross-carrier answer is one card per program

// Thinking off, effort low: the answer is a lookup in the sources given, and the agent waits for the first words.
// Sonnet 5.5 rejects {type: "disabled"} with a 400; its "off" is "between_tools" (effort high or below). Opus 5.5 and
// Fable can't turn thinking off: the field is left out (adaptive, kept short by effort low).
export function thinkingFor(model) {
  if (/^claude-sonnet-5-5/.test(model)) return { type: "between_tools" };
  if (/^claude-(opus-5-5|fable-)/.test(model)) return null;
  return { type: "disabled" };
}
export const MESSAGES = {
  notConfigured: "Ask the Guides isn't set up yet. The eligibility check still works.",
  unavailable: "Ask the Guides is unavailable right now. The eligibility check still works; please try again later.",
  overCap: "Ask the Guides has reached today's spending limit and is back at midnight UTC (7 pm Central). "
    + "The eligibility check still works.",
  rate: (n) => `You've asked ${n} questions in the last hour. Please wait a few minutes before asking another.`,
  busy: "The answer service is busy. Please try again in a minute.",
  failed: "The answer couldn't be finished. Please try again.",
};

let SYSTEM = null;
const system = () => (SYSTEM ??= systemPrompt(CHAT));

// The model client: { messages: { create(params) -> async iterable of the Messages API's stream events } }, the
// shape of the Anthropic SDK's messages.create({stream: true}). Tests replace it with a fake.
//
// The real one is a direct fetch to the Messages API, NOT the Anthropic SDK, for a measured reason (round 45,
// cloudflare/scripts/bench_chat.mjs, main-thread CPU per answer on the 40 live answers): with the SDK the Worker's own
// CPU was 4.4-4.6 ms a request on average, p95 8.6-9.4 ms, max 14-18 ms -- against the Free plan's 10 ms -- and 1.5 ms
// without it. The SDK's request building and stream decoding cost about 3 ms an answer; this parser reads only the
// "data:" lines it needs. Retries: none (the agent sees "busy, try again"); timeout 60 s.
export const API_URL = "https://api.anthropic.com/v1/messages";
export const API_VERSION = "2026-10-21";

async function* sseEvents(body) {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      for (const line of block.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5));
        if (ev.type === "error") {
          const e = new Error("model stream error");
          e.status = ev.error && ev.error.type === "overloaded_error" ? 529 : 500;
          throw e;
        }
        yield ev;
      }
    }
  }
}

const fetchClient = (env) => ({ messages: { create: async (params) => {
  const r = await fetch(API_URL, { method: "POST", signal: AbortSignal.timeout(60_000), body: JSON.stringify(params),
    headers: { "content-type": "application/json", "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": API_VERSION } });
  if (!r.ok || !r.body) {
    if (r.body) await r.body.cancel().catch(() => {});      // the API's error text is never read, logged or forwarded
    const e = new Error("model call failed");
    e.status = r.status;
    throw e;
  }
  return sseEvents(r.body);
} } });

let clientFactory = async (env) => fetchClient(env);
export function setChatClientFactory(fn) { clientFactory = fn; }

const num = (v, d) => (Number.isFinite(Number(v)) && String(v).trim() !== "" ? Number(v) : d);
const iso = (ms) => new Date(ms).toISOString().slice(0, 19) + "+00:00";

function errorJson(status, error, extra = {}) {
  return new Response(JSON.stringify({ error, ...extra }), {
    status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}

/** The cost guard's one D1 read: [questions this session asked in the last hour, today's spend]. */
async function usageSoFar(env, sid, nowMs) {
  const dayStart = iso(Date.UTC(new Date(nowMs).getUTCFullYear(), new Date(nowMs).getUTCMonth(), new Date(nowMs).getUTCDate()));
  const [a, b] = await env.DB.batch([
    env.DB.prepare("SELECT count(*) AS n FROM chat_log WHERE received_at >= ?1 AND session = ?2").bind(iso(nowMs - 3600_000), sid),
    env.DB.prepare("SELECT coalesce(sum(cost_usd), 0) AS usd FROM chat_log WHERE received_at >= ?1").bind(dayStart),
  ]);
  return [a.results[0].n, b.results[0].usd];
}

function modelError(e) {
  const status = e && typeof e.status === "number" ? e.status : 0;
  console.error("chat: model call failed --", status || (e && e.name) || "error");
  return status === 429 || status === 529 || status >= 500 ? MESSAGES.busy : MESSAGES.failed;
}

/**
 * POST /api/chat. `readJson(request, max)` and `HttpError` come from routes.js; `who` = {email, name, admin, sid?}.
 */
export async function postChat(request, env, who, ctx, { readJson, HttpError, nowIso }) {
  const body = await readJson(request, 32 * 1024);
  let req;
  try {
    req = parseChatBody(body);
  } catch (e) {
    if (e instanceof ChatInputError) throw new HttpError(400, e.message);
    throw e;
  }
  if (!env.ANTHROPIC_API_KEY) return errorJson(503, MESSAGES.notConfigured);
  const sid = who.sid || who.email || "anonymous";
  const t0 = Date.now();
  let asked, spent;
  try {
    [asked, spent] = await usageSoFar(env, sid, t0);
  } catch (e) {
    console.error("chat: chat_log read failed --", e && e.message);
    return errorJson(503, MESSAGES.unavailable);
  }
  const perHour = num(env.CHAT_RATE_PER_HOUR, 30), cap = num(env.CHAT_DAILY_CAP_USD, 3);
  if (spent >= cap) return errorJson(429, MESSAGES.overCap, { reason: "daily_cap" });
  if (asked >= perHour) return errorJson(429, MESSAGES.rate(asked), { reason: "rate_limit" });

  const ret = retrieve(CHAT, req.question, req.history);
  const model = env.CHAT_MODEL || DEFAULT_MODEL;
  const carriers = ret.route.mode === "all" ? [] : ret.route.programs.map((i) => CHAT.programs[i].display);
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const enc = new TextEncoder();
  const send = (obj) => writer.write(enc.encode(JSON.stringify(obj) + "\n")).catch(() => {});

  const run = async () => {
    let answer = "", firstMs = 0, usage = {}, stop = "error", status = "error";
    await send({ t: "start", carriers, mode: ret.route.mode });
    try {
      const client = await clientFactory(env);
      // the raw stream events: only the text pieces and the usage (message_start / message_delta) are read
      const stream = await client.messages.create({
        model, max_tokens: CHAT_MAX_TOKENS, stream: true,
        system: [{ type: "text", text: system(), cache_control: { type: "ephemeral" } }],
        messages: [{ role: "user", content: userMessage(CHAT, ret, req.question, req.history) }],
        output_config: { effort: "low" }, ...(thinkingFor(model) ? { thinking: thinkingFor(model) } : {}),
      });
      stop = null;
      for await (const ev of stream) {
        if (ev.type === "content_block_delta" && ev.delta.type === "text_delta" && ev.delta.text) {
          if (!firstMs) firstMs = Date.now() - t0;
          answer += ev.delta.text;
          await send({ t: "text", d: ev.delta.text });
        } else if (ev.type === "message_start") {
          usage = { ...(ev.message && ev.message.usage) };
        } else if (ev.type === "message_delta") {
          if (ev.usage) usage = { ...usage, ...Object.fromEntries(Object.entries(ev.usage).filter(([, v]) => v != null)) };
          if (ev.delta && ev.delta.stop_reason) stop = ev.delta.stop_reason;
        }
      }
      stop = stop || "end_turn";
      status = stop === "end_turn" ? "ok" : stop;
      const nums = citedNumbers(answer, ret.sources.length);
      const sent = ret.sources.filter((s) => nums.includes(s.n));
      const unverified = unverifiedQuotes(CHAT, answer, ret.sources);
      await send({ t: "done", citations: sent.map((s) => citation(CHAT, s, answer)), unverified, stop,
        cost_usd: Number(costUsd(model, usage).toFixed(6)), first_ms: firstMs, total_ms: Date.now() - t0 });
      return { answer, firstMs, usage, status, cited: [...new Set(sent.map((s) => citation(CHAT, s).carrier))],
        unverified: unverified.length };
    } catch (e) {
      await send({ t: "error", error: modelError(e) });
      return { answer, firstMs, usage, status, cited: [], unverified: 0 };
    } finally {
      await writer.close().catch(() => {});
    }
  };

  const logged = run().then(async (r) => {
    try {
      await env.DB.prepare("INSERT INTO chat_log (received_at, session, name, email, question, programs, cited, model, "
        + "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, first_ms, total_ms, status, "
        + "unverified_quotes) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17)")
        .bind(nowIso(), sid, who.name || "", who.email || "", req.question,
          JSON.stringify(ret.route.mode === "all" ? [] : ret.route.programs.map((i) => CHAT.programs[i].program)),
          JSON.stringify(r.cited), model, r.usage.input_tokens || 0, r.usage.output_tokens || 0,
          r.usage.cache_read_input_tokens || 0, r.usage.cache_creation_input_tokens || 0,
          Number(costUsd(model, r.usage).toFixed(6)), r.firstMs, Date.now() - t0, r.status, r.unverified).run();
    } catch (e) {
      console.error("chat: D1 write failed, chat_log row not saved --", e && e.message);
    }
  });
  if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(logged);
  return new Response(readable, { headers: { "content-type": "application/x-ndjson; charset=utf-8",
    "cache-control": "no-store", "x-content-type-options": "nosniff" } });
}

// ------------------------------------------------------------------------------------------------- admin CSV
export const CHAT_CSV_PART = 500;
const CSV_COLS = ["received_at", "name", "email", "session", "question", "programs", "cited", "model", "input_tokens",
  "output_tokens", "cache_read_tokens", "cost_usd", "first_ms", "total_ms", "status", "unverified_quotes"];
const csvCell = (v) => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** GET /api/admin/chat.csv?part=N: the chat log, CHAT_CSV_PART rows a part (oldest first), X-Chat-Parts says how many. */
export async function chatCsv(env, url) {
  const part = Math.max(1, parseInt(url.searchParams.get("part") || "1", 10) || 1);
  const [count, rows] = await env.DB.batch([
    env.DB.prepare("SELECT count(*) AS n FROM chat_log"),
    env.DB.prepare(`SELECT ${CSV_COLS.join(", ")} FROM chat_log ORDER BY received_at, id LIMIT ?1 OFFSET ?2`)
      .bind(CHAT_CSV_PART, (part - 1) * CHAT_CSV_PART),
  ]);
  const parts = Math.max(1, Math.ceil(count.results[0].n / CHAT_CSV_PART));
  const lines = rows.results.map((r) => CSV_COLS.map((c) => csvCell(r[c])).join(","));
  const body = (part === 1 ? CSV_COLS.join(",") + "\r\n" : "") + lines.map((l) => l + "\r\n").join("");
  return new Response(body, { headers: { "content-type": "text/csv; charset=utf-8", "cache-control": "no-store",
    "x-chat-parts": String(parts),
    "content-disposition": `attachment; filename="chat_log${parts > 1 ? `_part${part}` : ""}.csv"` } });
}
