// Cloudflare Access: who is calling (round 43 step 3).
//
// Access sits in front of the whole hostname and adds a signed JWT to every request it lets through, in the
// Cf-Access-Jwt-Assertion header. The Worker does not trust that header blindly (a request that reaches the Worker
// some other way would not have passed Access): it verifies the RS256 signature against the team's public keys
// (https://<ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs, cached per isolate), and the claims: iss is the team domain,
// aud contains this application's AUD tag, exp is in the future (nbf, when present, is not), and there is an email.
//
// Local development only: DEV_AUTH_EMAIL stands in for a token when the request is plain http to localhost /
// 127.0.0.1 / [::1] -- never true of a request Cloudflare routes to a deployed Worker (those are https to the
// custom domain). Keep DEV_AUTH_EMAIL out of wrangler.toml: set it in .dev.vars or with `wrangler dev --var`.

const JWKS_TTL_MS = 10 * 60 * 1000;       // keys are re-read every 10 minutes ...
const REFETCH_MIN_MS = 30 * 1000;         // ... or on an unknown key id, at most every 30 s (a forged kid can't storm)
const LEEWAY_S = 30;                      // clock skew allowed on exp / nbf

export class AuthError extends Error {
  constructor(message, status = 401) { super(message); this.status = status; }
}

let jwks = { url: "", at: 0, keys: new Map() };     // per isolate

/** Tests only: forget the cached keys. */
export function resetJwksCache() { jwks = { url: "", at: 0, keys: new Map() }; }

function b64urlBytes(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const b64urlJson = (s) => JSON.parse(new TextDecoder().decode(b64urlBytes(s)));

async function loadKeys(url, fetchImpl) {
  const res = await fetchImpl(url, { cf: { cacheTtl: 300 } });
  if (!res.ok) throw new AuthError(`Access keys unavailable (${res.status})`, 503);
  const body = await res.json();
  const keys = new Map();
  for (const k of body.keys || []) {
    if (k.kty !== "RSA" || !k.kid || !k.n || !k.e) continue;
    const key = await crypto.subtle.importKey("jwk", { kty: "RSA", n: k.n, e: k.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    keys.set(k.kid, key);
  }
  jwks = { url, at: Date.now(), keys };
}

async function keyFor(teamDomain, kid, fetchImpl) {
  const url = `https://${teamDomain}/cdn-cgi/access/certs`;
  const age = Date.now() - jwks.at;
  if (jwks.url !== url || age > JWKS_TTL_MS || (!jwks.keys.has(kid) && age > REFETCH_MIN_MS)) {
    await loadKeys(url, fetchImpl);
  }
  return jwks.keys.get(kid) || null;
}

/** The verified claims of an Access JWT, or an AuthError. */
export async function verifyAccessJwt(token, { teamDomain, aud, now = Date.now() / 1000, fetchImpl = fetch }) {
  const parts = token.split(".");
  if (parts.length !== 3) throw new AuthError("malformed token");
  let header, payload;
  try {
    header = b64urlJson(parts[0]);
    payload = b64urlJson(parts[1]);
  } catch {
    throw new AuthError("malformed token");
  }
  if (header.alg !== "RS256" || typeof header.kid !== "string") throw new AuthError("unexpected token algorithm");
  const key = await keyFor(teamDomain, header.kid, fetchImpl);
  if (!key) throw new AuthError("unknown signing key");
  let sig;
  try { sig = b64urlBytes(parts[2]); } catch { throw new AuthError("malformed token"); }
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, sig,
    new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  if (!ok) throw new AuthError("bad signature");
  if (payload.iss !== `https://${teamDomain}`) throw new AuthError("wrong issuer");
  const auds = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!auds.includes(aud)) throw new AuthError("wrong audience");
  if (typeof payload.exp !== "number" || now > payload.exp + LEEWAY_S) throw new AuthError("token expired");
  if (typeof payload.nbf === "number" && now + LEEWAY_S < payload.nbf) throw new AuthError("token not yet valid");
  if (typeof payload.email !== "string" || !payload.email) throw new AuthError("no email in token (service token?)", 403);
  return payload;
}

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** {email, admin, dev} for the caller, or throws AuthError. */
export async function identify(request, env, { fetchImpl = fetch } = {}) {
  const url = new URL(request.url);
  let email;
  let dev = false;
  if (env.DEV_AUTH_EMAIL && url.protocol === "http:" && LOOPBACK.has(url.hostname)) {
    email = env.DEV_AUTH_EMAIL;
    dev = true;
  } else {
    // round 43 step 3: wrangler.toml ships placeholders ("REPLACE-WITH-..."): those count as not configured too
    const unset = (v) => !v || /^REPLACE-|TBD/i.test(String(v));
    if (unset(env.ACCESS_TEAM_DOMAIN) || unset(env.ACCESS_AUD)) throw new AuthError("Access is not configured", 500);
    const token = request.headers.get("Cf-Access-Jwt-Assertion");
    if (!token) throw new AuthError("no Access token");
    email = (await verifyAccessJwt(token, { teamDomain: env.ACCESS_TEAM_DOMAIN, aud: env.ACCESS_AUD, fetchImpl })).email;
  }
  email = email.trim().toLowerCase();
  const admins = String(env.ADMIN_EMAILS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  return { email, admin: admins.includes(email), dev };
}
