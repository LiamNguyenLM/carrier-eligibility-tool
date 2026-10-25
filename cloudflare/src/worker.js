// cfig-eligibility: the Carrier Eligibility Tool's Worker (round 43 step 3).
//
// The static site (web/dist: the page and the Pyodide engine) is served by Workers Static Assets without running
// this code at all; wrangler.toml's run_worker_first = ["/api/*"] sends only the API here. Cloudflare Access sits in
// front of the hostname for both; the API also verifies Access's token itself (access.js).
import { handleApi } from "./routes.js";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) return handleApi(request, env, ctx, url);
    // Not reached for asset requests in production (run_worker_first); kept for `wrangler dev` setups and tests.
    return env.ASSETS.fetch(request);
  },
};
