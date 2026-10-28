// The shared-password gate (round 44 step 1, Liam 2026-10-25): what protects the tool until Cloudflare Access is on
// (AUTH_MODE = "password" in wrangler.toml; "access" later). The same protection Railway had -- one password for the
// agents -- plus a second one for the admin routes.
//
// In password mode the Worker runs first for EVERY path (wrangler.toml run_worker_first = true): no page, script,
// engine bundle, rules data or API answer leaves without a valid session.
//   GET  /login, POST /login   the login page; the agent password gives an agent session, the admin password an admin
//                              one (feedback download, weekly counts); an optional name fills the page's "Your name"
//   GET  /logout               ends the session
//   anything else              a valid session -> the static site or the API; none -> /login (a page) or 401
// The session is a cookie: "v1.<payload>.<HMAC-SHA256 over it with SESSION_SECRET>", HttpOnly, Secure, SameSite=Lax,
// 7 days. Changing SESSION_SECRET ends every session. Repeated wrong passwords from one address are locked out for a
// while (D1 table login_failures). Secrets (wrangler secret put, never in wrangler.toml or git): APP_PASSWORD,
// ADMIN_PASSWORD, SESSION_SECRET. A missing or weak one fails closed: every path refuses, and the login page says the
// tool is not set up yet.

export const COOKIE = "cfig_session";
export const SESSION_DAYS = 7;
export const MAX_FAILURES = 10;               // wrong passwords from one address ...
export const FAILURE_WINDOW_S = 15 * 60;      // ... within 15 minutes lock it out ...
export const LOCKOUT_S = 15 * 60;             // ... for 15 minutes
const enc = new TextEncoder();

export function authMode(env) {
  const m = String(env.AUTH_MODE || "access").trim().toLowerCase();
  return m === "password" || m === "access" ? m : "invalid";
}

/** null when the password gate can run, else why not (never shown to a visitor in detail). */
export function notConfigured(env) {
  if (!env.APP_PASSWORD || !env.ADMIN_PASSWORD || !env.SESSION_SECRET) return "a secret is missing";
  if (String(env.SESSION_SECRET).length < 32) return "SESSION_SECRET is shorter than 32 characters";
  if (String(env.APP_PASSWORD).length < 8 || String(env.ADMIN_PASSWORD).length < 8) return "a password is under 8 characters";
  if (env.APP_PASSWORD === env.ADMIN_PASSWORD) return "the agent and admin passwords are the same";
  return null;
}

const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_")
  .replace(/=+$/, "");
function unb64url(s) {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

const keys = new Map();                       // per isolate: SESSION_SECRET -> its HMAC key
async function hmacKey(secret) {
  if (!keys.has(secret)) {
    keys.set(secret, await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" },
      false, ["sign", "verify"]));
  }
  return keys.get(secret);
}

/** The cookie value for a session. */
export async function signSession(payload, secret) {
  const body = b64url(enc.encode(JSON.stringify(payload)));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode("v1." + body));
  return `v1.${body}.${b64url(sig)}`;
}

/** The session's payload, or null: a wrong signature, a tampered payload, another secret, expired, malformed. */
export async function verifySession(value, secret, now = Date.now() / 1000) {
  if (typeof value !== "string" || value.length > 2048) return null;
  const parts = value.split(".");
  if (parts.length !== 3 || parts[0] !== "v1") return null;
  try {
    const ok = await crypto.subtle.verify("HMAC", await hmacKey(secret), unb64url(parts[2]),
      enc.encode("v1." + parts[1]));           // constant-time inside WebCrypto
    if (!ok) return null;
    const p = JSON.parse(new TextDecoder().decode(unb64url(parts[1])));
    if (typeof p.exp !== "number" || now >= p.exp) return null;
    if (p.role !== "agent" && p.role !== "admin") return null;
    return p;
  } catch {
    return null;
  }
}

/** Is `given` the password? Compared as HMACs, in constant time (WebCrypto's verify), whatever the lengths. */
async function samePassword(given, expected, secret) {
  const key = await hmacKey(secret);
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(String(given)));
  return crypto.subtle.verify("HMAC", key, mac, enc.encode(String(expected)));
}

function cookieOf(request, name) {
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return null;
}

const setCookie = (value, maxAge) => `${COOKIE}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Lax`;

/** The caller's session ({role, name, exp}) or null. */
export async function sessionOf(request, env) {
  return verifySession(cookieOf(request, COOKIE), env.SESSION_SECRET);
}

/** Round 45: a stable id for this login (the chat's per-session rate limit): the first 16 hex of the cookie's
 * SHA-256. Not secret, and the cookie can't be rebuilt from it. */
export async function sessionKey(request) {
  const c = cookieOf(request, COOKIE) || "";
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(c)));
  return [...d.slice(0, 8)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** A same-site path to go back to after the login (never another site). */
export function safeNext(next) {
  const s = String(next || "/");
  return s.startsWith("/") && !s.startsWith("//") && !s.startsWith("/\\") && !/[\r\n]/.test(s)
    && !s.startsWith("/login") && !s.startsWith("/logout") ? s : "/";
}

const clientIp = (request) => request.headers.get("cf-connecting-ip") || "unknown";

/** Seconds left on this address's lockout (0: none). D1 trouble never locks anyone out. */
async function lockedFor(env, ip, now) {
  try {
    const row = await env.DB.prepare("SELECT locked_until FROM login_failures WHERE ip = ?1").bind(ip).first();
    return row && row.locked_until > now ? row.locked_until - now : 0;
  } catch (e) {
    console.error("login_failures read failed --", e);
    return 0;
  }
}

async function recordFailure(env, ip, now) {
  try {
    // a new window when the last one is over; the lockout starts at the MAX_FAILURES-th failure in a window
    await env.DB.prepare(
      "INSERT INTO login_failures (ip, failures, window_start, locked_until) VALUES (?1, 1, ?2, 0) "
      + "ON CONFLICT(ip) DO UPDATE SET "
      + "failures = CASE WHEN window_start <= ?2 - ?3 THEN 1 ELSE failures + 1 END, "
      + "window_start = CASE WHEN window_start <= ?2 - ?3 THEN ?2 ELSE window_start END, "
      + "locked_until = CASE WHEN window_start > ?2 - ?3 AND failures + 1 >= ?4 THEN ?2 + ?5 ELSE locked_until END")
      .bind(ip, now, FAILURE_WINDOW_S, MAX_FAILURES, LOCKOUT_S).run();
  } catch (e) {
    console.error("login_failures write failed --", e);
  }
}

async function clearFailures(env, ip) {
  try {
    await env.DB.prepare("DELETE FROM login_failures WHERE ip = ?1").bind(ip).run();
  } catch (e) {
    console.error("login_failures clear failed --", e);
  }
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  "'": "&#39;" }[c]));

/** The login page (no script, nothing from the site: it is shown before any session exists). */
export function loginPage({ error = "", next = "/", configured = true, status = 200 } = {}) {
  const form = configured ? `
    <form method="post" action="/login">
      <input type="hidden" name="next" value="${esc(safeNext(next))}">
      <label>Password<input type="password" name="password" autocomplete="current-password" required autofocus></label>
      <label>Your name (optional)<input type="text" name="name" maxlength="80" autocomplete="name"></label>
      <button type="submit">Sign in</button>
    </form>` : `<p class="error">This tool isn't set up yet. Please tell Liam.</p>`;
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Carrier Eligibility Tool - sign in</title>
<style>
  body { font-family: system-ui, sans-serif; background: #f6f7f9; color: #1d2430; margin: 0; }
  main { max-width: 360px; margin: 12vh auto; background: #fff; padding: 28px 32px; border-radius: 10px;
         box-shadow: 0 1px 4px rgba(0,0,0,.12); }
  h1 { font-size: 1.25rem; margin: 0 0 18px; } label { display: block; margin: 0 0 14px; font-size: .92rem; }
  input { display: block; width: 100%; box-sizing: border-box; margin-top: 4px; padding: 8px; font-size: 1rem; }
  button { width: 100%; padding: 9px; font-size: 1rem; background: #2b5fd9; color: #fff; border: 0; border-radius: 6px; }
  .error { color: #a01919; background: #fdecec; padding: 8px 10px; border-radius: 6px; font-size: .92rem; }
</style></head><body><main><h1>Carrier Eligibility Tool</h1>
${error ? `<p class="error">${esc(error)}</p>` : ""}${form}
</main></body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store",
    "x-frame-options": "DENY", "referrer-policy": "same-origin" } });
}

const WRONG = "That password isn't right.";

/** POST /login. */
export async function login(request, env, now = Math.floor(Date.now() / 1000)) {
  const ip = clientIp(request);
  let form;
  try {
    form = await request.formData();
  } catch {
    return loginPage({ error: WRONG, status: 400 });
  }
  const next = safeNext(form.get("next"));
  const wait = await lockedFor(env, ip, now);
  if (wait > 0) {
    return loginPage({ error: `Too many wrong passwords. Try again in ${Math.ceil(wait / 60)} minutes.`, next,
      status: 429 });
  }
  const given = String(form.get("password") || "");
  let role = null;
  if (given && await samePassword(given, env.ADMIN_PASSWORD, env.SESSION_SECRET)) role = "admin";
  else if (given && await samePassword(given, env.APP_PASSWORD, env.SESSION_SECRET)) role = "agent";
  if (!role) {
    await recordFailure(env, ip, now);
    return loginPage({ error: WRONG, next, status: 401 });
  }
  await clearFailures(env, ip);
  const name = String(form.get("name") || "").trim().slice(0, 80);
  const value = await signSession({ role, name, iat: now, exp: now + SESSION_DAYS * 86400 }, env.SESSION_SECRET);
  return new Response(null, { status: 303, headers: { location: next, "set-cookie": setCookie(value, SESSION_DAYS * 86400),
    "cache-control": "no-store" } });
}

/** GET /logout. */
export function logout() {
  return new Response(null, { status: 303, headers: { location: "/login", "set-cookie": setCookie("", 0),
    "cache-control": "no-store" } });
}

/** No session: a page visit goes to the login page; anything else (a script, the bundle, the API) gets 401. */
export function refuse(request, url) {
  const wantsPage = request.method === "GET" && (url.pathname === "/" || url.pathname.endsWith(".html")
    || (request.headers.get("accept") || "").includes("text/html")) && !url.pathname.startsWith("/api/");
  if (wantsPage) {
    return new Response(null, { status: 302, headers: { location: `/login?next=${encodeURIComponent(url.pathname
      + url.search)}`, "cache-control": "no-store" } });
  }
  const api = url.pathname.startsWith("/api/");
  return new Response(api ? JSON.stringify({ error: "login required" }) : "login required\n", { status: 401,
    headers: { "content-type": api ? "application/json; charset=utf-8" : "text/plain; charset=utf-8",
      "cache-control": "no-store" } });
}
