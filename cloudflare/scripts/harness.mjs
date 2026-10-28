// A Worker environment in plain Node, for the tests and the CPU benchmark (round 43 step 3): env.DB is the node:sqlite
// D1 stand-in loaded with the migrations, env.ASSETS a stub, and Access is a test RS256 key pair whose JWKS is served
// by a stubbed fetch() -- so every request still goes through the full token check. Round 44b: the placement tables
// are no longer in D1 but in the Worker's bundle, so loadWorker() builds that module from the CSVs first.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { D1Stub } from "./lib.mjs";
import { DEFAULT_CSV_DIR as CSV_DIR, writePlacementModule } from "./build_placement.mjs";
import { writeChatModule } from "./build_chat_index.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
export const TEAM = "cfig-test.cloudflareaccess.com";
export const AUD = "test-aud-0123456789abcdef";

const b64url = (bytes) => Buffer.from(bytes).toString("base64url");

export async function makeAccess() {
  const pair = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const kid = "test-key-1";
  const jwks = { keys: [{ kty: "RSA", kid, alg: "RS256", use: "sig", n: jwk.n, e: jwk.e }] };
  let fetches = 0;
  const fetchStub = async (url) => {
    fetches++;
    if (String(url) !== `https://${TEAM}/cdn-cgi/access/certs`) return new Response("no", { status: 404 });
    return new Response(JSON.stringify(jwks), { headers: { "content-type": "application/json" } });
  };
  async function token(claims = {}, { key = pair.privateKey, header = {} } = {}) {
    const now = Math.floor(Date.now() / 1000);
    const h = b64url(JSON.stringify({ alg: "RS256", kid, typ: "JWT", ...header }));
    const p = b64url(JSON.stringify({ aud: [AUD], email: "agent@cfigtx.com", exp: now + 3600, iat: now, nbf: now,
      iss: `https://${TEAM}`, sub: "u-1", type: "app", identity_nonce: "x", country: "US", ...claims }));
    const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${h}.${p}`));
    return `${h}.${p}.${b64url(new Uint8Array(sig))}`;
  }
  return { token, fetchStub, fetches: () => fetches, otherKey: async () => (await crypto.subtle.generateKey({
    name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
  true, ["sign", "verify"])).privateKey };
}

/** The D1 stand-in with every migration applied (0003 drops the placement tables again), then extraSql. */
export function makeDb(extraSql = []) {
  const db = new D1Stub(":memory:");
  const migDir = join(HERE, "..", "migrations");
  for (const f of readdirSync(migDir).filter((x) => x.endsWith(".sql")).sort()) db.sqlite.exec(readFileSync(join(migDir, f), "utf8"));
  db.sqlite.exec("BEGIN");
  for (const s of extraSql) db.sqlite.exec(s);
  db.sqlite.exec("COMMIT");
  return db;
}

/**
 * {worker: the Worker's default export, built: what was built}, with its placement module (cloudflare/build/placement_data.js) built from csvDir
 * first -- what wrangler's [build] step does before a deploy. A dynamic import, because routes.js imports the module
 * statically and it must exist before routes.js is linked.
 */
export async function loadWorker(csvDir = CSV_DIR) {
  const built = writePlacementModule(csvDir);
  built.chat = writeChatModule();                      // round 45: Ask the Guides' material, the same way
  const mod = await import("../src/worker.js");
  return { worker: mod.default, built };
}

export function makeEnv(db, vars = {}) {
  return { DB: db, ASSETS: { fetch: async () => new Response("asset", { status: 200 }) }, ACCESS_TEAM_DOMAIN: TEAM,
    ACCESS_AUD: AUD, ADMIN_EMAILS: "liam@cfigtx.com, JONATHAN-ADDRESS-TBD@cfigtx.com", ...vars };
}

export const BASE = "https://eligibility.cfigtx.com";

export function req(path, { method = "GET", token, body, type = "application/json", headers = {}, base = BASE } = {}) {
  const h = { ...headers };
  if (token) h["Cf-Access-Jwt-Assertion"] = token;
  if (body !== undefined) h["content-type"] = type;
  return new Request(base + path, { method, headers: h, body: body === undefined ? undefined
    : typeof body === "string" ? body : JSON.stringify(body) });
}

export const DEFAULT_CSV_DIR = CSV_DIR;
