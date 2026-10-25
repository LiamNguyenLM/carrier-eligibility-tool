#!/usr/bin/env node
// Round 43 step 2: a static server for web/dist on localhost, with an optional stand-in for the Worker's
// /api/* routes (--mock-api) for the parity harness (the real Worker: npx wrangler dev). No network beyond
// 127.0.0.1.
//
//   node tools/serve.mjs [--dir dist] [--port 8765] [--mock-api] [--placement-delay-ms 0]
//
// --mock-api: GET /api/whoami -> {email: "tester@example.com", admin: true}; POST /api/placement -> a made-up panel
// (web/tools/placement_panel.json if present; no HawkSoft data); POST /api/usage and /api/feedback -> 204 / {ok: true}, kept in
// memory and listed by GET /__posts (test only). GET /api/admin/feedback.csv -> a CSV of the feedback posts.

import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".wasm": "application/wasm",
  ".zip": "application/zip", ".gz": "application/gzip", ".map": "application/json", ".svg": "image/svg+xml",
};

export function startServer({ dir, port = 0, mockApi = false, placementDelayMs = 0 } = {}) {
  const root = path.resolve(dir);
  const posts = [];
  let panel = null;
  const panelFile = path.join(path.dirname(fileURLToPath(import.meta.url)), "placement_panel.json");
  if (mockApi && fs.existsSync(panelFile)) panel = JSON.parse(fs.readFileSync(panelFile, "utf8")).panel;

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost");
    const send = (code, body, type = "application/json; charset=utf-8") => {
      res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store" });
      res.end(body);
    };
    if (url.pathname.startsWith("/api/") || url.pathname === "/__posts") {
      if (!mockApi) return send(404, JSON.stringify({ error: "no Worker here" }));
      const body = req.method === "POST" ? await readBody(req) : null;
      if (url.pathname === "/__posts") return send(200, JSON.stringify(posts));
      if (url.pathname === "/api/whoami") return send(200, JSON.stringify({ email: "tester@example.com", admin: true }));
      if (url.pathname === "/api/placement" && req.method === "POST") {
        posts.push({ path: url.pathname, body });
        if (placementDelayMs) await new Promise((r) => setTimeout(r, placementDelayMs));
        return send(200, JSON.stringify(panel));
      }
      if ((url.pathname === "/api/usage" || url.pathname === "/api/feedback") && req.method === "POST") {
        posts.push({ path: url.pathname, body });
        return url.pathname === "/api/usage" ? send(204, "") : send(200, JSON.stringify({ ok: true }));
      }
      if (url.pathname === "/api/admin/feedback.csv") {
        const rows = posts.filter((p) => p.path === "/api/feedback").map((p) => p.body);
        const cols = ["ts", "name", "carrier", "verdict", "choice", "comment"];
        const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => JSON.stringify(String(r[c] ?? ""))).join(","))];
        return send(200, csv.join("\n"), "text/csv; charset=utf-8");
      }
      return send(404, JSON.stringify({ error: "unknown route" }));
    }
    let rel = decodeURIComponent(url.pathname);
    if (rel.endsWith("/")) rel += "index.html";
    const file = path.join(root, rel);
    if (!file.startsWith(root)) return send(403, "forbidden", "text/plain");
    fs.readFile(file, (err, data) => {
      if (err) return send(404, "not found", "text/plain");
      res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream",
                           "Cache-Control": "no-cache" });
      res.end(data);
    });
  });
  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => {
      const { port: p } = server.address();
      resolve({ server, port: p, url: `http://127.0.0.1:${p}/`, posts, close: () => server.close() });
    });
  });
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const s = Buffer.concat(chunks).toString("utf8");
      try { resolve(s ? JSON.parse(s) : null); } catch { resolve(s); }
    });
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const a = process.argv.slice(2);
  const opt = (k, d) => (a.includes(k) ? a[a.indexOf(k) + 1] : d);
  const s = await startServer({
    dir: path.resolve(WEB, opt("--dir", "dist")), port: Number(opt("--port", 8765)),
    mockApi: a.includes("--mock-api"), placementDelayMs: Number(opt("--placement-delay-ms", 0)),
  });
  console.log(`serving ${opt("--dir", "dist")} at ${s.url}${a.includes("--mock-api") ? " (mock /api)" : ""}`);
}
