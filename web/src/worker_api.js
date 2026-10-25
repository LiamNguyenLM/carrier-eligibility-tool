// The Worker's endpoints (another draft builds the Worker). The check never depends on them: placement times out
// after 2 s and is then not shown; usage failures are ignored; whoami failing shows no email.

const PLACEMENT_TIMEOUT_MS = 2000;

async function postJson(path, body, { timeoutMs = 8000 } = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      signal: ctl.signal, credentials: "same-origin",
    });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    const text = await r.text();
    return text ? JSON.parse(text) : null;
  } finally {
    clearTimeout(timer);
  }
}

// -> the panel dict ({title, basis, picks, usual, footer}) or null (none, error or timeout)
export async function placement(body) {
  try {
    const panel = await postJson("/api/placement", body, { timeoutMs: PLACEMENT_TIMEOUT_MS });
    return panel && typeof panel === "object" && panel.title ? panel : null;
  } catch {
    return null;
  }
}

export async function usage(body) {
  try { await postJson("/api/usage", body); } catch { /* ignored */ }
}

// -> true when the Worker took the report
export async function feedback(record) {
  await postJson("/api/feedback", record);
  return true;
}

// -> {email, admin} or null
export async function whoami() {
  try {
    const r = await fetch("/api/whoami", { credentials: "same-origin" });
    if (!r.ok) return null;
    const j = await r.json();
    return j && typeof j.email === "string" ? j : null;
  } catch {
    return null;
  }
}

export async function buildInfo(url) {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}
