// The /api routes (round 43 step 3). Every one needs a verified Access identity (access.js); the admin ones also an
// address in ADMIN_EMAILS.
//
//   GET  /api/whoami              {email, admin}
//   POST /api/usage               one row per check (usage_log.record()'s fields; the browser makes no model call)
//   POST /api/feedback            one "This looks wrong" report (feedback.record()'s fields) + the agent's email
//   POST /api/placement           placement.panel()'s dict, or null (placement.js; the tables are in the bundle)
//   GET  /api/admin/feedback.csv  the reports, feedback.to_csv()'s columns (+ email last), 300 a part (?part=N)
//   GET  /api/admin/weekly        checks and reports per ISO week
//   POST /api/chat                Ask the Guides: one question, answered as a stream (chat_route.js, round 45)
//   GET  /api/admin/chat.csv      the chat log, 500 questions a part (?part=N)
//
// Round 44b (Liam, 2026-10-25): a D1 write that fails is never fatal. A usage row is logged and dropped (202); a
// feedback report answers 503 "Couldn't save -- try again later." so the agent can resend. The placement panel never
// reads D1, and the gate's lockout counter (session.js) logs and carries on.
import { AuthError, identify } from "./access.js";
import { CSV_HEADER, feedbackCsvLine } from "./csv.js";
import { ageBand, buildPanel, covaBand, loadPanelTables, monthIndex, parsePlacementBody, pyCmp, pyStrip } from "./placement.js";
// Generated from rules_data/placement/*.csv before every deploy / dev run (wrangler.toml [build]); git-ignored.
import PLACEMENT from "../build/placement_data.js";
import { chatCsv, postChat } from "./chat_route.js";

export const CHOICES = ["Should be Eligible", "Should be Ineligible", "Should be Refer", "Not sure"];
const LIMITS = { usage: 16 * 1024, feedback: 64 * 1024, placement: 64 * 1024 };

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const json = (data, status = 200, extra = {}) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
});

/** Python's datetime.now(timezone.utc).isoformat(timespec="seconds"). */
export const nowIso = (d = new Date()) => d.toISOString().slice(0, 19) + "+00:00";

/** The body as JSON, refusing more than `max` bytes (before and while reading) and anything but JSON. */
async function readJson(request, max) {
  const type = request.headers.get("content-type") || "";
  if (!/^application\/json\b/i.test(type)) throw new HttpError(415, "send Content-Type: application/json");
  const declared = Number(request.headers.get("content-length"));
  if (declared > max) throw new HttpError(413, `body over ${max} bytes`);
  if (!request.body) throw new HttpError(400, "empty body");
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      reader.cancel().catch(() => {});
      throw new HttpError(413, `body over ${max} bytes`);
    }
    chunks.push(value);
  }
  const buf = new Uint8Array(size);
  let off = 0;
  for (const c of chunks) { buf.set(c, off); off += c.byteLength; }
  try {
    return JSON.parse(new TextDecoder().decode(buf));
  } catch {
    throw new HttpError(400, "body is not JSON");
  }
}

// ----------------------------------------------------------------------------------------------- field checks
const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
function str(v, name, max = 2000) {
  if (v === undefined || v === null) return "";
  if (typeof v !== "string") throw new HttpError(400, `${name} must be a string`);
  if (v.length > max) throw new HttpError(400, `${name} is over ${max} characters`);
  return v;
}
function strList(v, name, max = 200) {
  if (v === undefined || v === null) return [];
  if (!Array.isArray(v) || v.length > max) throw new HttpError(400, `${name} must be a list (at most ${max})`);
  return v.map((x) => (typeof x === "string" ? x : JSON.stringify(x)));
}
function num(v, name, { min = 0, max = 1e9, int = false } = {}) {
  if (v === undefined || v === null) return 0;
  if (typeof v !== "number" || !Number.isFinite(v) || v < min || v > max || (int && !Number.isInteger(v))) {
    throw new HttpError(400, `${name} must be ${int ? "an integer" : "a number"} in [${min}, ${max}]`);
  }
  return v;
}
const round2 = (v) => Number(v.toFixed(2));
const tsOr = (v, name) => {
  const s = str(v, name, 40);
  if (s && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(s)) throw new HttpError(400, `${name} must be an ISO time`);
  return s || nowIso();
};

// ----------------------------------------------------------------------------------------------- the routes
async function postUsage(request, env, who) {
  const b = await readJson(request, LIMITS.usage);
  if (!isObj(b)) throw new HttpError(400, "body must be a JSON object");
  const timings = {};
  if (b.timings !== undefined && b.timings !== null) {
    if (!isObj(b.timings) || Object.keys(b.timings).length > 50) throw new HttpError(400, "timings must be an object (at most 50 stages)");
    for (const [k, v] of Object.entries(b.timings)) timings[str(k, "timings key", 64)] = round2(num(v, `timings.${k}`, { max: 86400 }));
  }
  const row = [nowIso(), who.email, tsOr(b.ts, "ts"), str(b.app_version, "app_version", 64),
    round2(num(b.wall_s, "wall_s", { max: 86400 })), num(b.carriers, "carriers", { max: 10000, int: true }),
    JSON.stringify(timings)];
  let r;
  try {
    r = await env.DB.prepare("INSERT INTO usage (received_at, email, ts, app_version, wall_s, carriers, timings) "
      + "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)").bind(...row).run();
  } catch (e) {
    // round 44b: a usage row is bookkeeping -- D1 refusing it (e.g. the free tier's daily write limit) must not show
    // as an error anywhere. Logged, and answered 202 so the page carries on as for any other answer.
    console.error("usage: D1 write failed, row not saved --", e && e.message);
    return json({ ok: false, saved: false }, 202);
  }
  return json({ ok: true, id: r.meta.last_row_id }, 201);
}

export const FEEDBACK_NOT_SAVED = "Couldn’t save — try again later.";

async function postFeedback(request, env, who) {
  const b = await readJson(request, LIMITS.feedback);
  if (!isObj(b)) throw new HttpError(400, "body must be a JSON object");
  const pd = b.property_details ?? {};
  if (!isObj(pd)) throw new HttpError(400, "property_details must be an object");
  let checked = null;
  if (b.checked_topics !== undefined && b.checked_topics !== null) checked = strList(b.checked_topics, "checked_topics");
  if (b.kind === "chat") return saveFeedback(env, chatFeedbackRow(b, who));
  const choice = CHOICES.includes(b.choice) ? b.choice : "Not sure";             // feedback.record()'s rule
  const row = { received_at: nowIso(), email: who.email, ts: tsOr(b.ts, "ts"), app_version: str(b.app_version, "app_version", 64),
    name: pyStrip(str(b.name, "name", 200)), property_details: JSON.stringify(pd), carrier: str(b.carrier, "carrier", 300),
    display_name: str(b.display_name, "display_name", 300), verdict: str(b.verdict, "verdict", 100),
    reasons: JSON.stringify(strList(b.reasons, "reasons")), deciding_rows: JSON.stringify(strList(b.deciding_rows, "deciding_rows")),
    model: str(b.model, "model", 100), rules_table: b.rules_table ? 1 : 0,
    checked_topics: checked === null ? null : JSON.stringify(checked), choice, comment: pyStrip(str(b.comment, "comment", 20000)) };
  row.csv_row = feedbackCsvLine(row);
  return saveFeedback(env, row);
}

// Round 45: "This answer looks wrong" under an Ask the Guides answer. Same table and CSV, kind = 'chat': the CSV's
// verdict column says CHAT, its carrier column the carriers the answer cited, its reasons the question, and
// property_details holds the question and the answer.
export const CHAT_CHOICES = ["The answer is wrong", "A citation is wrong", "It didn't answer the question", "Not sure"];
function chatFeedbackRow(b, who) {
  const question = str(b.question, "question", 1000), answer = str(b.answer, "answer", 8000);
  const row = { received_at: nowIso(), email: who.email, ts: tsOr(b.ts, "ts"), app_version: str(b.app_version, "app_version", 64),
    name: pyStrip(str(b.name, "name", 200)), property_details: JSON.stringify({ question, answer }),
    carrier: strList(b.carriers, "carriers", 50).join("; ").slice(0, 300), display_name: "Ask the Guides", verdict: "CHAT",
    reasons: JSON.stringify([question]), deciding_rows: "[]", model: str(b.model, "model", 100), rules_table: 0,
    checked_topics: null, choice: CHAT_CHOICES.includes(b.choice) ? b.choice : "Not sure",
    comment: pyStrip(str(b.comment, "comment", 20000)) };
  row.csv_row = feedbackCsvLine(row);
  row.kind = "chat";
  return row;
}

async function saveFeedback(env, row) {
  const cols = Object.keys(row);
  let r;
  try {
    r = await env.DB.prepare(`INSERT INTO feedback (${cols.join(", ")}) VALUES (${cols.map((_, i) => "?" + (i + 1)).join(", ")})`)
      .bind(...Object.values(row)).run();
  } catch (e) {
    // round 44b: the agent must know the report did not arrive (the page keeps what they typed), so not a 202
    console.error("feedback: D1 write failed, report not saved --", e && e.message);
    return json({ ok: false, saved: false, error: FEEDBACK_NOT_SAVED }, 503);
  }
  return json({ ok: true, id: r.meta.last_row_id }, 201);
}

async function postPlacement(request, env) {
  const b = await readJson(request, LIMITS.placement);
  let req;
  try {
    req = parsePlacementBody(b);
  } catch (e) {
    throw new HttpError(400, e.message);
  }
  const year = parseInt(req.asOf.slice(0, 4), 10);
  // round 44b: the tables are bundled into the Worker (build_placement.mjs), so the panel never touches D1
  const T = loadPanelTables(PLACEMENT, { zip5: req.pd.zip, county: req.pd.county, ageB: ageBand(year, req.pd.year_built),
    covaB: covaBand(req.pd.dwelling_amount), asof: monthIndex(req.asOf) });
  return json(buildPanel(req.results, req.pd, req.asOf, T));
}

// ---- admin: the CSV feedback.to_csv() writes (lines stored at write time, csv.js), and the weekly counts
// D1 joins the stored lines, 400 reports to a string (well under D1's 2 MB value limit), so the Worker handles a few
// strings, not one object per report: one object per report made 1,000 reports cost 5-17 ms of Worker CPU.
const CSV_CHUNK = 400;
// Round 43 step 3: the Worker's CPU still grows with the bytes it moves (about 2 KB a report): 1,000 reports at once
// measured 15 ms, over the Free plan's 10 ms. So the reports come CSV_PART at a time (?part=N, 1 = the first, with
// the header; X-Feedback-Parts says how many), and the page's "Download feedback" link fetches every part into one
// file.
export const CSV_PART = 300;
async function feedbackCsv(env, url) {
  const part = Math.max(1, parseInt(url.searchParams.get("part") || "1", 10) || 1);
  const [count, rows] = await env.DB.batch([
    env.DB.prepare("SELECT count(*) AS n FROM feedback"),
    env.DB.prepare(
      "SELECT (rn - 1) / ?1 AS chunk, group_concat(csv_row || char(13, 10), '' ORDER BY rn) AS body "
      + "FROM (SELECT csv_row, row_number() OVER (ORDER BY ts, id) AS rn FROM feedback) "
      + "WHERE rn > ?2 AND rn <= ?3 GROUP BY chunk ORDER BY chunk")
      .bind(CSV_CHUNK, (part - 1) * CSV_PART, part * CSV_PART)]);
  const parts = Math.max(1, Math.ceil(count.results[0].n / CSV_PART));
  const body = (part === 1 ? CSV_HEADER + "\r\n" : "") + rows.results.map((r) => r.body).join("");
  return new Response(body, { headers: { "content-type": "text/csv; charset=utf-8", "cache-control": "no-store",
    "x-feedback-parts": String(parts),
    "content-disposition": `attachment; filename="feedback_log${parts > 1 ? `_part${part}` : ""}.csv"` } });
}

/** "2026-W43" and that week's Monday for a "YYYY-MM-DD" (UTC) date. */
export function isoWeek(day) {
  const d = new Date(day + "T00:00:00Z");
  const dow = (d.getUTCDay() + 6) % 7;                                  // Monday 0
  const monday = new Date(d.getTime() - dow * 86400000);
  const thursday = new Date(monday.getTime() + 3 * 86400000);
  const year = thursday.getUTCFullYear();
  const jan1 = Date.UTC(year, 0, 1);
  const week = 1 + Math.floor((thursday.getTime() - jan1) / (7 * 86400000));
  return { week: `${year}-W${String(week).padStart(2, "0")}`, start: monday.toISOString().slice(0, 10) };
}

async function weekly(env) {
  // one row per week out of D1 (the Monday on or before each day), not one per day or per check
  const q = (t) => env.DB.prepare(`SELECT date(substr(received_at, 1, 10), '-6 days', 'weekday 1') AS day, count(*) AS n `
    + `FROM ${t} GROUP BY day`);
  const [u, f] = await env.DB.batch([q("usage"), q("feedback")]);
  const weeks = new Map();
  const add = (rows, key) => {
    for (const { day, n } of rows) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day || "")) continue;
      const w = isoWeek(day);
      if (!weeks.has(w.week)) weeks.set(w.week, { week: w.week, start: w.start, checks: 0, feedback: 0 });
      weeks.get(w.week)[key] += n;
    }
  };
  add(u.results, "checks");
  add(f.results, "feedback");
  const list = [...weeks.values()].sort((a, b) => pyCmp(a.week, b.week));
  return json({ weeks: list, totals: { checks: list.reduce((s, w) => s + w.checks, 0),
    feedback: list.reduce((s, w) => s + w.feedback, 0) }, basis: "received_at, UTC weeks starting Monday" });
}

const ROUTES = {
  // round 44: + name, mode and the logout link (Access's in access mode, the gate's in password mode)
  "GET /api/whoami": async (req, env, who) => json({ email: who.email, admin: who.admin, name: who.name || "",
    mode: who.mode || "access", logout: who.mode === "password" ? "/logout" : "/cdn-cgi/access/logout" }),
  "POST /api/usage": postUsage,
  "POST /api/feedback": postFeedback,
  "POST /api/placement": postPlacement,
  "GET /api/admin/feedback.csv": async (req, env) => feedbackCsv(env, new URL(req.url)),
  "GET /api/admin/weekly": async (req, env) => weekly(env),
  "POST /api/chat": (req, env, who, ctx) => postChat(req, env, who, ctx, { readJson, HttpError, nowIso }),
  "GET /api/admin/chat.csv": async (req, env) => chatCsv(env, new URL(req.url)),
};

export async function handleApi(request, env, ctx, url = new URL(request.url), known = null) {
  // round 44: in password mode the gate (session.js) has already identified the caller
  let who = known;
  try {
    if (!who) who = await identify(request, env);
  } catch (e) {
    if (e instanceof AuthError) return json({ error: e.message }, e.status);
    console.error("auth failed --", e);
    return json({ error: "auth failed" }, 500);
  }
  const route = ROUTES[`${request.method} ${url.pathname}`];
  if (!route) {
    const known = Object.keys(ROUTES).some((k) => k.endsWith(" " + url.pathname));
    return json({ error: known ? "method not allowed" : "not found" }, known ? 405 : 404);
  }
  if (url.pathname.startsWith("/api/admin/") && !who.admin) return json({ error: "admins only" }, 403);
  try {
    return await route(request, env, who, ctx);
  } catch (e) {
    if (e instanceof HttpError) return json({ error: e.message }, e.status);
    console.error(`${request.method} ${url.pathname} failed --`, e);
    return json({ error: "internal error" }, 500);
  }
}
