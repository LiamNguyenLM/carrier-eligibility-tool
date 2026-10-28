// cfig-eligibility: the Carrier Eligibility Tool's Worker (round 43 step 3; the password gate round 44 step 1).
//
// wrangler.toml's AUTH_MODE picks who may in:
//   "password" (Liam, 2026-10-25, until Access is on): the Worker runs first for every path (run_worker_first = true)
//              and session.js lets nothing out -- page, script, engine bundle, rules data, API -- without a session
//              cookie from the login page.
//   "access"   Cloudflare Access sits in front of the hostname for everything; the static site is served as it is
//              and the API also verifies Access's token itself (access.js), failing closed.
// Anything else fails closed: 503 for every path.
import { handleApi } from "./routes.js";
import { authMode, login, loginPage, logout, notConfigured, refuse, safeNext, sessionKey, sessionOf } from "./session.js";

const isApi = (url) => url.pathname === "/api" || url.pathname.startsWith("/api/");

/** A gated static file: the site's own response, never kept in a shared cache. */
async function asset(request, env) {
  const res = await env.ASSETS.fetch(request);
  const out = new Response(res.body, res);
  out.headers.set("cache-control", "private, no-cache");       // the browser keeps it and revalidates (ETag)
  return out;
}

async function passwordMode(request, env, ctx, url) {
  if (notConfigured(env)) {
    // fail closed: no secret, no tool -- every path, the login page included, says so
    return isApi(url) ? new Response(JSON.stringify({ error: "not configured" }), { status: 503,
      headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } })
      : loginPage({ configured: false, status: 503 });
  }
  if (url.pathname === "/login") {
    if (request.method === "POST") return login(request, env);
    if (request.method === "GET") {
      if (await sessionOf(request, env)) {
        return new Response(null, { status: 303, headers: { location: safeNext(url.searchParams.get("next")) } });
      }
      return loginPage({ next: url.searchParams.get("next") || "/" });
    }
    return new Response("method not allowed\n", { status: 405 });
  }
  if (url.pathname === "/logout") return logout();
  const session = await sessionOf(request, env);
  if (!session) return refuse(request, url);
  if (isApi(url)) {
    const who = { email: "", name: session.name || "", admin: session.role === "admin", mode: "password",
      sid: url.pathname === "/api/chat" ? await sessionKey(request) : "" };      // round 45: the chat's rate limit
    return handleApi(request, env, ctx, url, who);
  }
  return asset(request, env);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const mode = authMode(env);
    if (mode === "password") return passwordMode(request, env, ctx, url);
    if (mode === "access") {
      if (isApi(url)) return handleApi(request, env, ctx, url);
      return env.ASSETS.fetch(request);          // Access in front decides who gets here
    }
    return new Response("This tool isn't set up yet (AUTH_MODE). Please tell Liam.\n", { status: 503,
      headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
  },
};
