#!/usr/bin/env node
// Round 43 step 2 (Liam, 2026-10-24): build the static page.
//
//   node web/build.mjs [--repo .] [--out web/dist]     (npm run build at the repo root)
//   --no-sizes: skip the gzip / brotli measurements (brotli 11 on the wasm takes a while)
//
// dist/ = index.html + src/ + pyodide/ (the npm package's core files) + engine.tar.gz (one gzipped tar that
// pyodide.unpackArchive(buf, "gztar") unpacks, paths relative to the repo root) + build.json {commit, built_at}.
// The placement tables (rules_data/placement/) must never be in dist/: the build fails if any file there is.
// Prints raw / gzip / brotli sizes of every part and writes <out>.report.json next to dist/.
//
// Read-only on the repo: it reads files and runs `git rev-parse` only.

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

const WEB = path.dirname(fileURLToPath(import.meta.url));

// Everything the engine reads besides its own .py files, relative to the repo root: engine.bundle.data_files() and
// the manifest (verification/test_web_build.py fails if the two lists differ). "*" matches within one path segment.
export const ENGINE_DATA_FILES = [
  "rules_data/carrier_rules_*.csv",
  "rules_data/*field_map*.csv",
  "rules_data/cfig_knowledge.csv",
  "texas_counties.csv",
  "zip_counties.csv",
  "rules_data/engine_manifest.json",
];
// What may never ship: HawkSoft placement data (the Worker serves the panel).
const FORBIDDEN = [/(^|\/)rules_data\/placement(\/|$)/, /(^|\/)placement_[^/]*\.csv$/i, /(^|\/)\.env/];


const PYODIDE_FILES = ["pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
const PAGE_FILES = ["index.html", "src/app.js", "src/engine.js", "src/markdown.js", "src/worker_api.js", "src/styles.css"];

function args(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--no-sizes") out.noSizes = true;
    else if (a.startsWith("--")) out[a.slice(2)] = argv[++i];
  }
  return out;
}

function fail(msg) { console.error("BUILD FAILED: " + msg); process.exit(1); }

function globRepo(repo, pattern) {
  const dir = path.posix.dirname(pattern);
  const base = path.posix.basename(pattern);
  const abs = path.join(repo, dir);
  if (!base.includes("*")) return fs.existsSync(path.join(abs, base)) ? [pattern] : [];
  if (!fs.existsSync(abs)) return [];
  const rx = new RegExp("^" + base.split("*").map((s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join("[^/]*") + "$");
  return fs.readdirSync(abs).filter((n) => rx.test(n) && fs.statSync(path.join(abs, n)).isFile()).sort()
    .map((n) => (dir === "." ? n : `${dir}/${n}`));
}

function walk(dir, rel = "") {
  const out = [];
  for (const n of fs.readdirSync(dir).sort()) {
    if (n === "__pycache__") continue;
    const p = path.join(dir, n);
    const r = rel ? `${rel}/${n}` : n;
    if (fs.statSync(p).isDirectory()) out.push(...walk(p, r));
    else out.push(r);
  }
  return out;
}

// ---- a minimal deterministic ustar writer (regular files only; Python's tarfile makes the directories) ----
function tarHeader(name, size) {
  const h = Buffer.alloc(512);
  let prefix = "";
  let nm = name;
  if (Buffer.byteLength(nm) > 100) {
    const cut = name.lastIndexOf("/", 155);
    prefix = name.slice(0, cut);
    nm = name.slice(cut + 1);
    if (Buffer.byteLength(nm) > 100 || Buffer.byteLength(prefix) > 155) fail("path too long for ustar: " + name);
  }
  const put = (s, off, len) => h.write(s, off, len, "utf8");
  const oct = (n, len) => n.toString(8).padStart(len - 1, "0") + "\0";
  put(nm, 0, 100);
  put(oct(0o644, 8), 100, 8);
  put(oct(0, 8), 108, 8);
  put(oct(0, 8), 116, 8);
  put(oct(size, 12), 124, 12);
  put(oct(0, 12), 136, 12);                 // mtime 0: the same bytes every build
  put("        ", 148, 8);
  put("0", 156, 1);
  put("ustar\0", 257, 6);
  put("00", 263, 2);
  put(prefix, 345, 155);
  let sum = 0;
  for (const b of h) sum += b;
  put(sum.toString(8).padStart(6, "0") + "\0 ", 148, 8);
  return h;
}

function tar(entries) {                       // [{name, data: Buffer}]
  const parts = [];
  for (const { name, data } of entries) {
    parts.push(tarHeader(name, data.length), data);
    const pad = (512 - (data.length % 512)) % 512;
    if (pad) parts.push(Buffer.alloc(pad));
  }
  parts.push(Buffer.alloc(1024));
  return Buffer.concat(parts);
}

const gz = (b) => zlib.gzipSync(b, { level: 9 });
const br = (b) => zlib.brotliCompressSync(b, {
  params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 11, [zlib.constants.BROTLI_PARAM_SIZE_HINT]: b.length },
});
const kb = (n) => (n / 1024).toFixed(1).padStart(9) + " KB";

function engineEntries(repo) {
  const files = [];
  const engineDir = path.join(repo, "engine");
  if (!fs.existsSync(engineDir)) fail(`${engineDir} does not exist`);
  for (const r of walk(engineDir)) if (r.endsWith(".py")) files.push(`engine/${r}`);
  const missing = [];
  for (const pat of ENGINE_DATA_FILES) {
    const hit = globRepo(repo, pat);
    if (!hit.length) missing.push(pat);
    files.push(...hit);
  }
  if (missing.length) fail("engine data files not found: " + missing.join(", ") + " (update ENGINE_DATA_FILES)");
  return files.map((name) => ({ name, data: fs.readFileSync(path.join(repo, name)) }));
}

function gitCommit(repo) {
  // Workers Builds sets WORKERS_CI_COMMIT_SHA (Cloudflare's build environment); else the checkout's HEAD
  if (process.env.WORKERS_CI_COMMIT_SHA) return process.env.WORKERS_CI_COMMIT_SHA.slice(0, 7);
  try {
    return execFileSync("git", ["-C", repo, "rev-parse", "--short=7", "HEAD"], { encoding: "utf8" }).trim();
  } catch {
    return "unknown";
  }
}

function main() {
  const a = args(process.argv.slice(2));
  const repo = path.resolve(a.repo || path.join(WEB, ".."));
  const out = path.resolve(a.out || path.join(WEB, "dist"));
  if (!fs.existsSync(repo)) fail("no repo at " + repo);
  // the bundle first: a forbidden or missing file fails the build before anything is written
  const entries = engineEntries(repo);
  const bad = entries.filter((e) => FORBIDDEN.some((rx) => rx.test(e.name)));
  if (bad.length) fail("forbidden files in the engine bundle: " + bad.map((e) => e.name).join(", "));
  const sizes = !a.noSizes;
  fs.rmSync(out, { recursive: true, force: true });
  fs.mkdirSync(out, { recursive: true });
  const report = { mode: "engine", parts: {} };
  const add = (part, rel, data, extra = {}) => {
    const dest = path.join(out, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, data);
    (report.parts[part] ||= []).push({ file: rel, raw: data.length, gzip: sizes ? gz(data).length : 0,
                                       brotli: sizes ? br(data).length : 0,
                                       ...extra });
  };

  for (const f of PAGE_FILES) add("page", f, fs.readFileSync(path.join(WEB, f)));
  const pyDir = path.join(repo, "node_modules", "pyodide");          // npm ci at the repo root
  const pyVersion = JSON.parse(fs.readFileSync(path.join(pyDir, "package.json"), "utf8")).version;
  if (pyVersion !== "0.28.3") fail("pyodide in node_modules is " + pyVersion + ", want 0.28.3 (npm ci)");
  for (const f of PYODIDE_FILES) add("pyodide", `pyodide/${f}`, fs.readFileSync(path.join(pyDir, f)));

  const tarBuf = tar(entries);
  const bundle = gz(tarBuf);
  const sha = createHash("sha256").update(bundle).digest("hex");
  add("engine bundle", "engine.tar.gz", bundle, {
    note: "shipped gzipped (gztar); raw/gzip/brotli of the tar inside below",
    tar_raw: tarBuf.length, tar_gzip: bundle.length, tar_brotli: sizes ? br(tarBuf).length : 0, files: entries.length,
  });
  report.bundle_files = entries.map((e) => ({ name: e.name, bytes: e.data.length }))
    .sort((x, y) => y.bytes - x.bytes);

  const build = { commit: gitCommit(repo), built_at: new Date().toISOString(), mode: report.mode,
                  pyodide: pyVersion, bundle_sha256: sha, bundle_files: entries.length };
  add("build.json", "build.json", Buffer.from(JSON.stringify(build, null, 1) + "\n"));

  // the placement tables are never shipped, whatever put them there
  const shipped = walk(out);
  const leaked = shipped.filter((f) => FORBIDDEN.some((rx) => rx.test(f)));
  if (leaked.length) fail("forbidden files in dist: " + leaked.join(", "));
  const placementNames = fs.existsSync(path.join(repo, "rules_data", "placement"))
    ? fs.readdirSync(path.join(repo, "rules_data", "placement")) : [];
  const sameName = [...shipped, ...entries.map((e) => e.name)]
    .filter((f) => placementNames.includes(path.posix.basename(f)));
  if (sameName.length) fail("a placement table's file name is in dist: " + sameName.join(", "));

  report.build = build;
  report.totals = {};
  console.log(`\n${report.mode} build -> ${out}   commit ${build.commit}   ${entries.length} files in the bundle`);
  console.log("part / file".padEnd(44) + "raw".padStart(12) + "gzip".padStart(12) + "brotli".padStart(12));
  for (const [part, files] of Object.entries(report.parts)) {
    const t = { raw: 0, gzip: 0, brotli: 0 };
    for (const f of files) {
      const raw = f.tar_raw ?? f.raw;
      const g = f.tar_raw ? f.tar_gzip : f.gzip;
      const b = f.tar_raw ? f.tar_brotli : f.brotli;
      t.raw += raw; t.gzip += g; t.brotli += b;
      console.log(("  " + f.file + (f.tar_raw ? " (the tar)" : "")).padEnd(44) + kb(raw) + kb(g) + kb(b));
    }
    report.totals[part] = t;
    console.log(("= " + part).padEnd(44) + kb(t.raw) + kb(t.gzip) + kb(t.brotli));
  }
  const all = Object.entries(report.totals)
    .reduce((s, [, t]) => ({ raw: s.raw + t.raw, gzip: s.gzip + t.gzip, brotli: s.brotli + t.brotli }),
            { raw: 0, gzip: 0, brotli: 0 });
  report.totals.first_load = all;
  console.log("= first load (everything)".padEnd(44) + kb(all.raw) + kb(all.gzip) + kb(all.brotli));
  console.log("placement tables: not in dist (checked)\n");
  fs.writeFileSync(out + ".report.json", JSON.stringify(report, null, 1));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
